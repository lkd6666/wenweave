"""Durable, provider-reported model-call accounting shared by all workflows."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import BaseMessage

from app.db.session import SessionLocal
from app.models.model_call_record import ModelCallRecord, ModelCallSource, ModelCallStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


def _usage_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _token_count(value: object) -> int | None:
    # ``bool`` is an ``int`` subclass, but is never a meaningful token count.
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _first_token(usage: Mapping[str, object], *names: str) -> int | None:
    for name in names:
        value = _token_count(usage.get(name))
        if value is not None:
            return value
    return None


def _usage_candidates(message: BaseMessage | object) -> list[Mapping[str, object]]:
    candidates: list[Mapping[str, object]] = []
    for value in (
        getattr(message, "usage_metadata", None),
        getattr(message, "response_metadata", None),
        getattr(message, "additional_kwargs", None),
    ):
        mapping = _usage_mapping(value)
        if mapping is None:
            continue
        candidates.append(mapping)
        for key in ("token_usage", "usage"):
            nested = _usage_mapping(mapping.get(key))
            if nested is not None:
                candidates.append(nested)
    return candidates


def _cache_tokens(usage: Mapping[str, object], *, write: bool) -> int | None:
    details = [
        mapping for key in ("input_token_details", "input_tokens_details", "prompt_tokens_details")
        if (mapping := _usage_mapping(usage.get(key))) is not None
    ]
    names = (
        ("cache_creation", "cache_creation_tokens", "cache_creation_input_tokens", "cache_write_tokens")
        if write else
        ("cache_read", "cache_read_tokens", "cache_read_input_tokens", "cached_tokens", "cached_input_tokens", "prompt_cache_hit_tokens")
    )
    for mapping in [*details, usage]:
        value = _first_token(mapping, *names)
        if value is not None:
            return value
    for mapping in [*details, usage]:
        # Tier counters are aliases of the aggregate, not additional tokens.
        tiers = [_first_token(mapping, f"{tier}_{'cache_creation' if write else 'cache_read'}")
                 for tier in ("priority", "flex")]
        if any(value is not None for value in tiers):
            return sum(value or 0 for value in tiers)
    return None


def _usage_fields(usage: Mapping[str, object]) -> tuple[int | None, int | None, int | None, int | None]:
    # LangChain normalizes OpenAI and Anthropic usage into ``input_tokens`` /
    # ``output_tokens``. Some compatible gateways preserve their native
    # response in ``response_metadata`` instead, where OpenAI calls them
    # ``prompt_tokens`` / ``completion_tokens``.
    input_tokens = _first_token(usage, "input_tokens", "prompt_tokens", "prompt_token_count")
    output_tokens = _first_token(
        usage,
        "output_tokens",
        "completion_tokens",
        "candidates_token_count",
        "completion_token_count",
    )
    cache_read = _cache_tokens(usage, write=False)
    cache_write = _cache_tokens(usage, write=True)
    # Anthropic native input_tokens counts only uncached input. LangChain's
    # input_token_details representation already includes reads and writes.
    if input_tokens is not None and _usage_mapping(usage.get("input_token_details")) is None:
        native_read = _first_token(usage, "cache_read_input_tokens")
        native_write = _first_token(usage, "cache_creation_input_tokens")
        if native_read is not None or native_write is not None:
            input_tokens += (native_read or 0) + (native_write or 0)
    return input_tokens, output_tokens, cache_read, cache_write


def _usage_from_mapping(usage: Mapping[str, object]) -> ModelUsage | None:
    input_tokens, output_tokens, cache_read, cache_write = _usage_fields(usage)
    if input_tokens is None or output_tokens is None or input_tokens <= 0:
        return None
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read or 0,
        cache_write_tokens=cache_write or 0,
    )


def usage_from_message(message: BaseMessage | object) -> ModelUsage | None:
    """Read provider-reported usage without replacing missing values by estimates."""
    fields: list[int | None] = [None, None, None, None]
    for usage in _usage_candidates(message):
        for index, value in enumerate(_usage_fields(usage)):
            if fields[index] is None and value is not None:
                fields[index] = value
    input_tokens, output_tokens, cache_read, cache_write = fields
    if input_tokens is None or output_tokens is None or input_tokens <= 0:
        return None
    return ModelUsage(input_tokens, output_tokens, cache_read or 0, cache_write or 0)


class ModelCallTracker:
    """Persist a model attempt at start and update its eventual terminal state."""

    def __init__(
        self,
        *,
        model_id: int,
        user_id: int | None,
        source: ModelCallSource,
        source_id: str = "",
    ) -> None:
        self.model_id = int(model_id)
        self.user_id = int(user_id) if user_id is not None else None
        self.source = source
        self.source_id = str(source_id or "")[:64]
        self.started_at = utcnow()
        self._finished = False
        self.record_id: int | None = None
        self._start()

    def complete(self, response: BaseMessage | object | None = None) -> None:
        self._finish(ModelCallStatus.COMPLETED, response=response)

    def fail(self, exc: BaseException) -> None:
        status = ModelCallStatus.CANCELLED if isinstance(exc, asyncio.CancelledError) else ModelCallStatus.FAILED
        self._finish(status, error_message=str(exc)[:512])

    def _start(self) -> None:
        """Record an in-flight request before the provider can outlive this worker."""
        db = SessionLocal()
        try:
            record = ModelCallRecord(
                model_id=self.model_id,
                user_id=self.user_id,
                source=self.source,
                source_id=self.source_id,
                status=ModelCallStatus.RUNNING,
                usage_reported=False,
                error_message="",
                started_at=self.started_at,
                finished_at=None,
            )
            db.add(record)
            db.commit()
            self.record_id = int(record.id)
        except Exception:
            # Model accounting remains non-critical. A failed accounting write
            # must not prevent the user request from reaching its provider.
            db.rollback()
        finally:
            db.close()

    def _finish(
        self,
        status: ModelCallStatus,
        *,
        response: BaseMessage | object | None = None,
        error_message: str = "",
    ) -> None:
        if self._finished:
            return
        self._finished = True
        usage = usage_from_message(response) if response is not None else None
        db = SessionLocal()
        try:
            record = db.get(ModelCallRecord, self.record_id) if self.record_id is not None else None
            if record is None:
                # Keep the historical best-effort behavior if writing the
                # start record failed but the terminal record can be stored.
                record = ModelCallRecord(
                    model_id=self.model_id,
                    user_id=self.user_id,
                    source=self.source,
                    source_id=self.source_id,
                    started_at=self.started_at,
                )
                db.add(record)
            record.status = status
            record.usage_reported = usage is not None
            record.input_tokens = usage.input_tokens if usage else None
            record.output_tokens = usage.output_tokens if usage else None
            record.cache_read_tokens = usage.cache_read_tokens if usage else None
            record.cache_write_tokens = usage.cache_write_tokens if usage else None
            record.error_message = error_message
            record.finished_at = utcnow()
            db.commit()
        except Exception:
            # Accounting must never turn a successful provider response into a
            # failed user workflow. The next request can still be recorded.
            db.rollback()
        finally:
            db.close()


async def invoke_with_accounting(
    awaitable: Any,
    *,
    model_id: int,
    user_id: int | None,
    source: ModelCallSource,
    source_id: str = "",
) -> Any:
    tracker = ModelCallTracker(model_id=model_id, user_id=user_id, source=source, source_id=source_id)
    try:
        response = await awaitable
    except BaseException as exc:
        tracker.fail(exc)
        raise
    tracker.complete(response)
    return response
