"""Measure raw and application-eligible candidates from a SearXNG verify service."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import httpx


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.image_search import (  # noqa: E402
    ImageSearchCandidate,
    fetch_candidate_image,
    fetch_candidate_preview,
    parse_search_results,
)


DEFAULT_QUERIES = ("城市公园", "新能源汽车", "中国山水")
MINIMUM_CANDIDATES = 6
MAX_SECONDS = 4.0


async def fetch_payload(client: httpx.AsyncClient, base_url: str, query: str) -> tuple[dict, float]:
    started = time.perf_counter()
    response = await client.get(
        f"{base_url.rstrip('/')}/search",
        params={
            "q": query,
            "categories": "images",
            "format": "json",
            "language": "zh-CN",
            "safesearch": 1,
            "pageno": 1,
        },
        headers={"Accept": "application/json"},
    )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("SearXNG did not return a JSON object")
    return payload, elapsed


async def verify_readability(
    samples: dict[str, ImageSearchCandidate],
) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for engine, candidate in samples.items():
        try:
            await fetch_candidate_preview(candidate)
            await fetch_candidate_image(candidate)
            outcomes[engine] = "preview_and_original_ok"
        except (httpx.HTTPError, ValueError, OSError) as exc:
            outcomes[engine] = f"failed: {exc}"
    return outcomes


async def verify(base_url: str, secret: str, queries: tuple[str, ...]) -> int:
    # Exercise the exact image-read fallback used by the application without
    # changing the caller's process or persistent environment.
    os.environ["SEARXNG_BASE_URL"] = base_url.rstrip("/")
    os.environ["SEARXNG_SECRET"] = secret
    get_settings.cache_clear()
    timeout = httpx.Timeout(MAX_SECONDS, connect=MAX_SECONDS)
    qualifying_queries: Counter[str] = Counter()
    report: list[dict[str, object]] = []
    samples: dict[str, ImageSearchCandidate] = {}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for query in queries:
            try:
                payload, elapsed = await fetch_payload(client, base_url, query)
                raw_counts = Counter(
                    str(item.get("engine") or "unknown")
                    for item in payload.get("results", [])
                    if isinstance(item, dict)
                )
                eligible = parse_search_results(payload, base_url=base_url)
                eligible_counts = Counter(item.engine for item in eligible)
                for candidate in eligible:
                    samples.setdefault(candidate.engine, candidate)
                for engine, count in eligible_counts.items():
                    if count >= MINIMUM_CANDIDATES and elapsed <= MAX_SECONDS:
                        qualifying_queries[engine] += 1
                report.append(
                    {
                        "query": query,
                        "elapsed_ms": round(elapsed * 1000),
                        "raw_results_by_engine": dict(sorted(raw_counts.items())),
                        "eligible_candidates_by_engine": dict(sorted(eligible_counts.items())),
                        "unresponsive_engines": payload.get("unresponsive_engines", []),
                    }
                )
            except (httpx.HTTPError, ValueError) as exc:
                report.append({"query": query, "error": str(exc)})

    accepted = sorted(engine for engine, count in qualifying_queries.items() if count >= 2)
    accepted_samples = {engine: samples[engine] for engine in accepted if engine in samples}
    readability = await verify_readability(accepted_samples)
    readable = sorted(engine for engine, outcome in readability.items() if outcome == "preview_and_original_ok")
    print(json.dumps({
        "queries": report,
        "accepted_engines": accepted,
        "readability_by_engine": readability,
        "production_engines": readable,
    }, ensure_ascii=False, indent=2))
    return 0 if readable else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--searxng-secret", required=True)
    parser.add_argument("--query", action="append", dest="queries")
    args = parser.parse_args()
    queries = tuple(args.queries or DEFAULT_QUERIES)
    return asyncio.run(verify(args.base_url, args.searxng_secret, queries))


if __name__ == "__main__":
    raise SystemExit(main())
