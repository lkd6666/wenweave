from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import timezone
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.security import create_scoped_token, decode_access_token
from app.services import local_uploads
from app.services.external_fetch import MAX_IMAGE_BYTES, PublicFetchError, fetch_public_image, normalize_public_https_url


IMAGE_SEARCH_SCOPE = "image-search-candidate"
IMAGE_SEARCH_CURSOR_SCOPE = "image-search-cursor"
IMAGE_SEARCH_NOTICE = "搜索结果来自互联网，版权归原作者或权利人所有；使用前请自行确认授权范围。"
MAX_SEARCH_RESPONSE_BYTES = 2 * 1024 * 1024
SEARCH_PAGE_SIZE = 12
MAX_SEARCH_CANDIDATES_PER_PAGE = 200
MAX_SEARCH_PAGES = 10
SEARCH_CURSOR_TTL_MINUTES = 120
IMAGE_SEARCH_AGENT_REFERENCE_TTL_SECONDS = 2 * 60 * 60


class ImageSearchError(ValueError):
    """SearXNG is unavailable or returned an unusable response."""


class ImageSearchTokenError(ValueError):
    """A signed search candidate is invalid for the requested operation."""


@dataclass(frozen=True)
class ImageSearchCandidate:
    id: str
    image_url: str
    preview_url: str
    source_page_url: str
    title: str
    engine: str
    width: int | None = None
    height: int | None = None
    image_format: str = ""


MAX_SEARCH_CACHE_ENTRIES = 64
# Cache normalized upstream pages, not the public orientation/page window. This
# lets editor pagination and Agent cursors reuse the same SearXNG response.
_search_cache: dict[tuple[str, int], tuple[float, tuple[ImageSearchCandidate, ...]]] = {}
_search_inflight: dict[tuple[str, int], asyncio.Task[tuple[ImageSearchCandidate, ...]]] = {}


def _configured_base_url() -> str:
    settings = get_settings()
    value = settings.SEARXNG_BASE_URL.strip().rstrip("/")
    if not value:
        value = f"http://127.0.0.1:{int(settings.SEARXNG_HOST_PORT)}"
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ImageSearchError("搜图服务地址无效") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.username or parsed.password or not host or parsed.query or parsed.fragment:
        raise ImageSearchError("搜图服务地址无效")
    if parsed.scheme == "http" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ImageSearchError("远程搜图服务必须使用 HTTPS")
    if parsed.scheme not in {"http", "https"}:
        raise ImageSearchError("搜图服务地址无效")
    return value


def _https_url(value: object) -> str:
    raw = str(value or "").strip()
    if raw.startswith("//"):
        raw = f"https:{raw}"
    try:
        return normalize_public_https_url(raw)
    except PublicFetchError:
        return ""


def _source_page_url(value: object, engine: str) -> str:
    source = _https_url(value)
    if source or engine.strip().lower() != "baidu images":
        return source

    # Baidu Images currently returns many HTTPS originals but reports their
    # publisher pages with an HTTP scheme. The page URL is only metadata and
    # a Referer; safely upgrade this trusted engine's standard HTTP URL rather
    # than dropping an otherwise valid HTTPS image candidate.
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "http"
        or parsed.username
        or parsed.password
        or not parsed.hostname
        or port not in {None, 80}
    ):
        return ""
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return _https_url(urlunsplit(("https", host, parsed.path or "/", parsed.query, "")))


def _dimensions(result: dict) -> tuple[int | None, int | None]:
    def positive(value: object) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    width = positive(result.get("width"))
    height = positive(result.get("height"))
    if width and height:
        return width, height
    resolution = result.get("resolution")
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        return positive(resolution[0]), positive(resolution[1])
    matched = re.search(r"(\d{2,6})\s*[xX×*]\s*(\d{2,6})", str(resolution or ""))
    return (positive(matched.group(1)), positive(matched.group(2))) if matched else (None, None)


def _matches_orientation(width: int | None, height: int | None, orientation: str) -> bool:
    if orientation == "any":
        return True
    if not width or not height:
        # Some engines (notably Brave and Flickr) do not expose dimensions in
        # their JSON result. Keep those candidates and let the UI label the
        # dimensions as unknown instead of dropping an otherwise valid image.
        return True
    ratio = width / height
    if orientation == "square":
        return 0.85 <= ratio <= 1.15
    if orientation == "landscape":
        return ratio > 1.15
    return ratio < 0.85


def _preview_url(value: object, base_url: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    joined = urljoin(base_url.rstrip("/") + "/", raw)
    parsed = urlsplit(joined)
    base = urlsplit(base_url)
    if parsed.scheme in {"http", "https"} and parsed.hostname == base.hostname and parsed.port == base.port:
        return joined
    external = _https_url(joined)
    return _searx_image_proxy_url(external, base_url) or external


def _searx_image_proxy_url(source_url: str, base_url: str | None = None) -> str:
    source = source_url.strip()
    secret = get_settings().SEARXNG_SECRET.strip()
    if not source or not secret:
        return ""
    base = (base_url or _configured_base_url()).rstrip("/")
    signature = hmac.new(secret.encode("utf-8"), source.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{base}/image_proxy?{urlencode({'url': source, 'h': signature})}"


async def _fetch_internal_proxy(client: httpx.AsyncClient, proxy_url: str) -> tuple[bytes, local_uploads.ImageInfo]:
    try:
        async with client.stream(
            "GET",
            proxy_url,
            headers={"Accept": "image/*", "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
        ) as response:
            if response.status_code >= 400:
                raise ImageSearchError(f"图片代理不可用（HTTP {response.status_code}）")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_IMAGE_BYTES:
                    raise ImageSearchError("图片超过 10MB 限制")
        data = bytes(body)
        return data, local_uploads.inspect_image(data)
    except local_uploads.LocalUploadError as exc:
        raise ImageSearchError(str(exc)) from exc
    except httpx.RequestError as exc:
        raise ImageSearchError("图片代理暂时不可用") from exc


def parse_search_results(
    payload: object,
    *,
    base_url: str,
    orientation: str = "any",
    max_results: int = MAX_SEARCH_CANDIDATES_PER_PAGE,
) -> list[ImageSearchCandidate]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ImageSearchError("搜图服务返回了无效数据")
    candidates: list[ImageSearchCandidate] = []
    seen: set[str] = set()
    for result in payload["results"]:
        if not isinstance(result, dict):
            continue
        engine = str(result.get("engine") or result.get("source") or "SearXNG").strip()[:80]
        image_url = _https_url(result.get("img_src") or result.get("image_src"))
        source_page_url = _source_page_url(result.get("url"), engine)
        if not image_url or not source_page_url or image_url in seen:
            continue
        width, height = _dimensions(result)
        if not _matches_orientation(width, height, orientation):
            continue
        preview_url = _preview_url(result.get("thumbnail_src") or image_url, base_url)
        if not preview_url:
            continue
        seen.add(image_url)
        candidates.append(ImageSearchCandidate(
            id=hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:20],
            image_url=image_url,
            preview_url=preview_url,
            source_page_url=source_page_url,
            title=str(result.get("title") or "图片搜索结果").strip()[:240],
            engine=engine,
            width=width,
            height=height,
            image_format=str(result.get("img_format") or result.get("format") or "").strip()[:24],
        ))
        if len(candidates) >= max(1, min(int(max_results), MAX_SEARCH_CANDIDATES_PER_PAGE)):
            break
    return candidates


def _cache_seconds() -> float:
    return max(0.0, min(float(get_settings().SEARXNG_SEARCH_CACHE_SECONDS), 600.0))


def _cached_page(query: str, page: int) -> tuple[ImageSearchCandidate, ...] | None:
    cached = _search_cache.get((query, page))
    if cached and time.monotonic() - cached[0] < _cache_seconds():
        return cached[1]
    if cached:
        _search_cache.pop((query, page), None)
    return None


def _store_cached_page(query: str, page: int, candidates: list[ImageSearchCandidate]) -> tuple[ImageSearchCandidate, ...]:
    value = tuple(candidates)
    _search_cache[(query, page)] = (time.monotonic(), value)
    if len(_search_cache) > MAX_SEARCH_CACHE_ENTRIES:
        oldest = min(_search_cache, key=lambda key: _search_cache[key][0])
        _search_cache.pop(oldest, None)
    return value


def _search_timeout_seconds() -> float:
    return float(get_settings().SEARXNG_TIMEOUT_SECONDS)


async def _fetch_search_page(
    query: str,
    page: int,
    *,
    base_url: str,
    timeout_seconds: float,
) -> tuple[ImageSearchCandidate, ...]:
    timeout = httpx.Timeout(max(0.1, timeout_seconds), connect=max(0.1, timeout_seconds))
    params = {
        "q": query,
        "categories": "images",
        "format": "json",
        "language": "zh-CN",
        "safesearch": 1,
        "pageno": page,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = await client.get(
                f"{base_url}/search",
                params=params,
                headers={"Accept": "application/json", "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
            )
            if response.status_code >= 400:
                raise ImageSearchError(f"搜图服务暂时不可用（HTTP {response.status_code}）")
            if len(response.content) > MAX_SEARCH_RESPONSE_BYTES:
                raise ImageSearchError("搜图服务返回的数据过大")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ImageSearchError("搜图服务返回了无效数据") from exc
    except ImageSearchError:
        raise
    except httpx.RequestError as exc:
        raise ImageSearchError("搜图服务暂时不可用") from exc
    return _store_cached_page(
        query,
        page,
        parse_search_results(payload, base_url=base_url, max_results=MAX_SEARCH_CANDIDATES_PER_PAGE),
    )


async def _get_search_page(
    query: str,
    page: int,
    *,
    base_url: str,
    deadline: float,
) -> tuple[ImageSearchCandidate, ...]:
    cached = _cached_page(query, page)
    if cached is not None:
        return cached
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise ImageSearchError("搜图服务响应超时")
    key = (query, page)
    loop = asyncio.get_running_loop()
    task = _search_inflight.get(key)
    if task is None or task.get_loop() is not loop or task.cancelled():
        task = loop.create_task(
            _fetch_search_page(
                query,
                page,
                base_url=base_url,
                timeout_seconds=min(_search_timeout_seconds(), remaining),
            )
        )
        _search_inflight[key] = task
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise ImageSearchError("搜图服务响应超时") from exc
    finally:
        if task.done() and _search_inflight.get(key) is task:
            _search_inflight.pop(key, None)


def _filter_candidates(candidates: tuple[ImageSearchCandidate, ...], orientation: str) -> list[ImageSearchCandidate]:
    return [item for item in candidates if _matches_orientation(item.width, item.height, orientation)]


async def search_image_page(
    query: str,
    page: int = 1,
    orientation: str = "any",
) -> tuple[list[ImageSearchCandidate], bool]:
    """Return one editor page and whether another candidate really exists."""
    try:
        page_value = int(page)
    except (TypeError, ValueError) as exc:
        raise ImageSearchError("搜图页码无效") from exc
    if page_value < 1 or page_value > 5:
        raise ImageSearchError("搜图页码必须是 1 到 5")
    if orientation not in {"any", "landscape", "portrait", "square"}:
        raise ImageSearchError("图片方向无效")
    query = str(query or "").strip()
    if len(query) < 2 or len(query) > 120:
        raise ImageSearchError("搜图关键词必须是 2 到 120 个字符")

    base_url = _configured_base_url()
    start = (page_value - 1) * SEARCH_PAGE_SIZE
    end = start + SEARCH_PAGE_SIZE
    continuation_end = end + 1
    deadline = asyncio.get_running_loop().time() + _search_timeout_seconds()
    collected: list[ImageSearchCandidate] = []
    seen: set[str] = set()
    last_error: ImageSearchError | None = None
    for upstream_page in range(1, MAX_SEARCH_PAGES + 1):
        try:
            candidates = await _get_search_page(query, upstream_page, base_url=base_url, deadline=deadline)
        except ImageSearchError as exc:
            last_error = exc
            if collected:
                break
            raise
        for candidate in _filter_candidates(candidates, orientation):
            if candidate.id in seen:
                continue
            seen.add(candidate.id)
            collected.append(candidate)
        if len(collected) >= continuation_end or len(candidates) < MAX_SEARCH_CANDIDATES_PER_PAGE:
            break
        if asyncio.get_running_loop().time() >= deadline:
            break
    if not collected and last_error is not None:
        raise last_error
    return collected[start:end], len(collected) > end


async def search_images(query: str, page: int = 1, orientation: str = "any") -> list[ImageSearchCandidate]:
    """Compatibility wrapper returning only the editor page items."""
    items, _ = await search_image_page(query, page, orientation)
    return items


def _cursor_cipher() -> Fernet:
    settings = get_settings()
    key_material = f"{settings.SECRET_KEY}:{IMAGE_SEARCH_CURSOR_SCOPE}:v1".encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material).digest()))


def issue_search_cursor(
    *,
    query: str,
    purpose: str,
    orientation: str,
    user_id: int,
    document_id: int,
    page: int,
    offset: int,
    seen_ids: set[str],
) -> str:
    sealed = _cursor_cipher().encrypt(
        json.dumps(
            {
                "query": query,
                "purpose": purpose,
                "orientation": orientation,
                "page": page,
                "offset": offset,
                "seen": list(seen_ids)[-MAX_SEARCH_PAGES * SEARCH_PAGE_SIZE :],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")
    return create_scoped_token(
        str(user_id),
        IMAGE_SEARCH_CURSOR_SCOPE,
        {"document_id": document_id, "cursor": sealed},
        expires_in_minutes=SEARCH_CURSOR_TTL_MINUTES,
    )


def decode_search_cursor(
    token: str,
    *,
    user_id: int,
    document_id: int,
    query: str,
    purpose: str,
    orientation: str,
) -> dict[str, object]:
    try:
        payload = decode_access_token(token)
        if payload.get("scope") != IMAGE_SEARCH_CURSOR_SCOPE or str(payload.get("sub")) != str(user_id):
            raise ImageSearchTokenError("搜图续搜游标无效")
        if int(payload.get("document_id") or 0) != int(document_id):
            raise ImageSearchTokenError("搜图续搜游标不属于当前文档")
        raw = _cursor_cipher().decrypt(str(payload.get("cursor") or "").encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
    except (jwt.PyJWTError, InvalidToken, UnicodeDecodeError, UnicodeEncodeError, ValueError, json.JSONDecodeError) as exc:
        raise ImageSearchTokenError("搜图续搜游标已失效，请重新搜索") from exc
    if not isinstance(value, dict):
        raise ImageSearchTokenError("搜图续搜游标无效")
    if (
        str(value.get("query") or "") != query
        or str(value.get("purpose") or "") != purpose
        or str(value.get("orientation") or "") != orientation
    ):
        raise ImageSearchTokenError("搜图续搜参数与首次搜索不一致")
    try:
        page = int(value.get("page") or 0)
        offset = int(value.get("offset") or 0)
    except (TypeError, ValueError) as exc:
        raise ImageSearchTokenError("搜图续搜游标无效") from exc
    if page < 1 or page > MAX_SEARCH_PAGES or offset < 0:
        raise ImageSearchTokenError("搜图续搜游标无效")
    seen = value.get("seen") if isinstance(value.get("seen"), list) else []
    return {"page": page, "offset": offset, "seen": {str(item) for item in seen if str(item)}}


async def search_images_with_cursor(
    query: str,
    *,
    purpose: str,
    orientation: str,
    cursor: str,
    limit: int,
    user_id: int,
    document_id: int,
) -> tuple[list[ImageSearchCandidate], str | None]:
    normalized_query = str(query or "").strip()
    if len(normalized_query) < 2 or len(normalized_query) > 120:
        raise ImageSearchError("搜图关键词必须是 2 到 120 个字符")
    limit_value = max(1, min(int(limit), SEARCH_PAGE_SIZE))
    if cursor:
        state = decode_search_cursor(
            cursor,
            user_id=user_id,
            document_id=document_id,
            query=normalized_query,
            purpose=purpose,
            orientation=orientation,
        )
        upstream_page = int(state["page"])
        offset = int(state["offset"])
        seen = set(state["seen"])
    else:
        upstream_page, offset, seen = 1, 0, set()

    base_url = _configured_base_url()
    deadline = asyncio.get_running_loop().time() + _search_timeout_seconds()
    items: list[ImageSearchCandidate] = []
    while upstream_page <= MAX_SEARCH_PAGES and len(items) < limit_value:
        try:
            raw_page = await _get_search_page(query=normalized_query, page=upstream_page, base_url=base_url, deadline=deadline)
        except ImageSearchError:
            if items:
                break
            raise
        filtered = _filter_candidates(raw_page, orientation)
        while offset < len(filtered) and len(items) < limit_value:
            candidate = filtered[offset]
            offset += 1
            if candidate.id in seen:
                continue
            seen.add(candidate.id)
            items.append(candidate)
        if len(items) >= limit_value:
            break
        if offset < len(filtered):
            break
        upstream_page += 1
        offset = 0
        if asyncio.get_running_loop().time() >= deadline:
            break

    has_more = upstream_page <= MAX_SEARCH_PAGES and (
        upstream_page < MAX_SEARCH_PAGES or offset < len(_filter_candidates(_cached_page(normalized_query, upstream_page) or (), orientation))
    )
    next_cursor = (
        issue_search_cursor(
            query=normalized_query,
            purpose=purpose,
            orientation=orientation,
            user_id=user_id,
            document_id=document_id,
            page=upstream_page,
            offset=offset,
            seen_ids=seen,
        )
        if has_more
        else None
    )
    return items, next_cursor


def issue_candidate_token(candidate: ImageSearchCandidate, *, user_id: int, document_id: int) -> str:
    candidate_data = {
        "id": candidate.id,
        "image_url": candidate.image_url,
        "preview_url": candidate.preview_url,
        "source_page_url": candidate.source_page_url,
        "title": candidate.title,
        "engine": candidate.engine,
        "width": candidate.width,
        "height": candidate.height,
        "image_format": candidate.image_format,
    }
    sealed_candidate = _candidate_cipher().encrypt(
        json.dumps(candidate_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return create_scoped_token(
        str(user_id),
        IMAGE_SEARCH_SCOPE,
        {
            "document_id": document_id,
            "candidate_id": candidate.id,
            "candidate": sealed_candidate,
        },
        expires_in_minutes=120,
    )


def _candidate_cipher() -> Fernet:
    settings = get_settings()
    key_material = f"{settings.SECRET_KEY}:{IMAGE_SEARCH_SCOPE}:v1".encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material).digest()))


def _candidate_reference_signature(value: str, *, user_id: int, document_id: int) -> str:
    key_material = f"{get_settings().SECRET_KEY}:{IMAGE_SEARCH_SCOPE}:reference:v1".encode("utf-8")
    message = f"{user_id}:{document_id}:{value}".encode("utf-8")
    return hmac.new(key_material, message, hashlib.sha256).hexdigest()[:32]


def issue_candidate_reference(
    output_id: str,
    index: int,
    *,
    user_id: int,
    document_id: int,
) -> str:
    """Issue a compact, signed pointer into a persisted search tool result.

    Full candidate capabilities are intentionally kept out of the model-visible
    tool message. The complete result is already stored by ``ToolOutputStore``;
    this reference lets the next tool resolve one item without copying a 1KB+
    token through a context window.
    """
    output = str(output_id or "").strip()
    position = int(index)
    if not output or position < 0:
        raise ImageSearchTokenError("搜图候选引用无效")
    expires = int(time.time()) + IMAGE_SEARCH_AGENT_REFERENCE_TTL_SECONDS
    value = f"{output}.{position}.{expires}"
    return f"{value}.{_candidate_reference_signature(value, user_id=user_id, document_id=document_id)}"


def decode_candidate_reference(
    reference: str,
    *,
    user_id: int,
    document_id: int,
) -> ImageSearchCandidate:
    """Resolve a short Agent reference from the durable tool-output payload."""
    raw = str(reference or "").strip()
    parts = raw.split(".")
    if len(parts) != 4:
        raise ImageSearchTokenError("搜图候选引用无效")
    output_id, index_text, expires_text, signature = parts
    value = f"{output_id}.{index_text}.{expires_text}"
    try:
        index = int(index_text)
        expires = int(expires_text)
    except (TypeError, ValueError) as exc:
        raise ImageSearchTokenError("搜图候选引用无效") from exc
    if not output_id or index < 0 or expires < int(time.time()):
        raise ImageSearchTokenError("搜图候选引用已失效，请重新搜索")
    expected = _candidate_reference_signature(value, user_id=user_id, document_id=document_id)
    if not hmac.compare_digest(signature, expected):
        raise ImageSearchTokenError("搜图候选引用无效")

    try:
        from app.db.session import SessionLocal
        from app.models.chat_tool_output import ChatToolOutput

        with SessionLocal() as db:
            stored = db.get(ChatToolOutput, output_id)
            if stored is None or int(stored.document_id) != int(document_id):
                raise ImageSearchTokenError("搜图候选引用已失效，请重新搜索")
            expires_at = stored.expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if (
                expires_at is None
                or expires_at.timestamp() < time.time()
            ):
                raise ImageSearchTokenError("搜图候选引用已失效，请重新搜索")
            payload = json.loads(stored.content or "{}")
    except ImageSearchTokenError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ImageSearchTokenError("搜图候选引用无效") from exc
    except Exception as exc:  # noqa: BLE001 - do not expose storage details to the Agent.
        raise ImageSearchTokenError("搜图候选引用暂时不可用") from exc

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or index >= len(items) or not isinstance(items[index], dict):
        raise ImageSearchTokenError("搜图候选引用无效")
    candidate_token = str(items[index].get("token") or "")
    if not candidate_token:
        raise ImageSearchTokenError("搜图候选引用无效")
    return decode_candidate_token(candidate_token, user_id=user_id, document_id=document_id)


def decode_candidate_reference_or_token(
    reference: str,
    *,
    user_id: int | None = None,
    document_id: int | None = None,
) -> ImageSearchCandidate:
    """Resolve the short Agent pointer and tolerate legacy field mix-ups.

    Older model turns occasionally put the full JWT in ``candidate_ref``
    instead of ``candidate_token``. A JWT has two separators, while the
    compact reference has three, so this compatibility path is unambiguous and
    still applies the normal user/document/expiry checks.
    """
    value = str(reference or "").strip()
    if value and value.count(".") == 2:
        return decode_candidate_token(value, user_id=user_id, document_id=document_id)
    return decode_candidate_reference(value, user_id=int(user_id or 0), document_id=int(document_id or 0))


def decode_candidate_token(token: str, *, user_id: int | None = None, document_id: int | None = None) -> ImageSearchCandidate:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise ImageSearchTokenError("搜图候选已失效，请重新搜索") from exc
    if payload.get("scope") != IMAGE_SEARCH_SCOPE:
        raise ImageSearchTokenError("搜图候选无效")
    if user_id is not None and str(payload.get("sub")) != str(user_id):
        raise ImageSearchTokenError("不能使用其他用户的搜图候选")
    try:
        token_document_id = int(payload.get("document_id") or 0)
    except (TypeError, ValueError) as exc:
        raise ImageSearchTokenError("搜图候选无效") from exc
    if document_id is not None and token_document_id != document_id:
        raise ImageSearchTokenError("搜图候选不属于当前文档")
    sealed_candidate = str(payload.get("candidate") or "")
    if sealed_candidate:
        try:
            raw_candidate = _candidate_cipher().decrypt(sealed_candidate.encode("ascii"))
            candidate_data = json.loads(raw_candidate.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError, json.JSONDecodeError, ValueError) as exc:
            raise ImageSearchTokenError("搜图候选无效") from exc
    else:
        # Compatibility for candidates issued immediately before encrypted
        # payloads were introduced. Their original two-hour expiry still
        # applies, and all newly issued tokens use the encrypted form.
        candidate_data = payload
    if not isinstance(candidate_data, dict):
        raise ImageSearchTokenError("搜图候选无效")
    image_url = _https_url(candidate_data.get("image_url"))
    source_page_url = _https_url(candidate_data.get("source_page_url"))
    preview_url = str(candidate_data.get("preview_url") or "").strip()
    candidate_id = str(candidate_data.get("id") or candidate_data.get("candidate_id") or "").strip()
    preview_parts = urlsplit(preview_url)
    if preview_parts.hostname in {"127.0.0.1", "localhost", "::1"} and preview_parts.path.startswith("/image_proxy"):
        # Re-sign old loopback proxy links when the configured host port has
        # changed (for example, from 8888 to 8088).
        preview_url = _searx_image_proxy_url(image_url) or preview_url
    if candidate_id != str(payload.get("candidate_id") or "").strip():
        raise ImageSearchTokenError("搜图候选无效")
    if not image_url or not source_page_url or not preview_url or not candidate_id:
        raise ImageSearchTokenError("搜图候选无效")
    try:
        width = int(candidate_data["width"]) if candidate_data.get("width") else None
        height = int(candidate_data["height"]) if candidate_data.get("height") else None
    except (TypeError, ValueError) as exc:
        raise ImageSearchTokenError("搜图候选无效") from exc
    return ImageSearchCandidate(
        id=candidate_id,
        image_url=image_url,
        preview_url=preview_url,
        source_page_url=source_page_url,
        title=str(candidate_data.get("title") or "图片搜索结果")[:240],
        engine=str(candidate_data.get("engine") or "SearXNG")[:80],
        width=width,
        height=height,
        image_format=str(candidate_data.get("image_format") or "")[:24],
    )


def candidate_payload(candidate: ImageSearchCandidate, token: str) -> dict:
    return {
        "id": candidate.id,
        "token": token,
        "preview_url": f"/api/image-search/preview?token={token}",
        "title": candidate.title,
        "source_page_url": candidate.source_page_url,
        "engine": candidate.engine,
        "width": candidate.width,
        "height": candidate.height,
        "format": candidate.image_format,
    }


async def fetch_candidate_image(candidate: ImageSearchCandidate) -> tuple[bytes, local_uploads.ImageInfo]:
    timeout_seconds = _search_timeout_seconds()
    timeout = httpx.Timeout(timeout_seconds, connect=timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        try:
            return await fetch_public_image(client, candidate.image_url, canonical_url=candidate.source_page_url)
        except PublicFetchError as direct_error:
            proxy_url = _searx_image_proxy_url(candidate.image_url)
            if not proxy_url:
                raise direct_error
            # The proxy occasionally races a remote thumbnail/image origin.
            # A short retry avoids forcing the Agent to duplicate a valid
            # candidate token while keeping the normal per-image timeout.
            for attempt in range(2):
                try:
                    return await _fetch_internal_proxy(client, proxy_url)
                except ImageSearchError:
                    if attempt:
                        raise
                    await asyncio.sleep(0.2)
    raise ImageSearchError("图片下载失败")


async def fetch_candidate_preview(candidate: ImageSearchCandidate) -> tuple[bytes, local_uploads.ImageInfo]:
    base_url = _configured_base_url()
    preview = candidate.preview_url
    parsed = urlsplit(preview)
    base = urlsplit(base_url)
    timeout_seconds = _search_timeout_seconds()
    timeout = httpx.Timeout(timeout_seconds, connect=timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        if parsed.hostname == base.hostname and parsed.port == base.port and parsed.scheme == base.scheme:
            try:
                return await _fetch_internal_proxy(client, preview)
            except ImageSearchError:
                # Some thumbnail CDNs reject proxy requests while the
                # validated original image remains available.
                if preview != candidate.image_url:
                    try:
                        return await fetch_public_image(client, candidate.image_url, canonical_url=candidate.source_page_url)
                    except PublicFetchError:
                        pass
                raise
        try:
            return await fetch_public_image(client, preview, canonical_url=candidate.source_page_url)
        except PublicFetchError as exc:
            raise ImageSearchError(str(exc)) from exc
