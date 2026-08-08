"""Shared, transactional conversion of HTML image references into durable URLs."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx
from bs4 import BeautifulSoup

from app.services import local_uploads


_CSS_URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


class ImageLocalizationError(ValueError):
    """An HTML image reference cannot be converted into a durable URL."""


@dataclass(frozen=True)
class StoredImage:
    """A persisted image and the opaque value needed to compensate it."""

    url: str
    handle: object


@dataclass(frozen=True)
class ImageLocalizationResult:
    html: str
    localized_count: int
    replacements: dict[str, str]
    stored_images: tuple[StoredImage, ...] = ()


ImageLoader = Callable[[str, httpx.AsyncClient], Awaitable[tuple[bytes, local_uploads.ImageInfo]]]
ImageStorer = Callable[[bytes, local_uploads.ImageInfo, str], StoredImage]
ImageCleaner = Callable[[StoredImage], None]
LocalSourcePredicate = Callable[[str], bool]


def _is_ignorable_source(source: str) -> bool:
    return not source or source.startswith("#")


def _srcset_source_spans(value: str) -> list[tuple[int, int, str]]:
    """Return URL spans from a conventional srcset value.

    A data URL contains a comma after its MIME type, so splitting blindly on
    commas would turn it into two image sources. Descriptors are left outside
    the returned spans, preserving them when a URL is replaced.
    """
    spans: list[tuple[int, int, str]] = []
    position = 0
    length = len(value)
    while position < length:
        while position < length and (value[position].isspace() or value[position] == ","):
            position += 1
        if position >= length:
            break

        start = position
        is_data_url = value[start:start + 5].lower() == "data:"
        while position < length:
            character = value[position]
            if character.isspace() or (character == "," and not is_data_url):
                break
            position += 1
        end = position
        source = value[start:end].strip()
        if source and not _is_ignorable_source(source):
            spans.append((start, end, source))

        # Consume descriptors up to the separator. A data URL only reaches
        # this branch after a descriptor or the end of the attribute.
        while position < length and value[position] != ",":
            position += 1
        if position < length:
            position += 1
    return spans


def _srcset_sources(value: str) -> list[str]:
    return [source for _start, _end, source in _srcset_source_spans(value)]


def _collect_sources(soup: BeautifulSoup) -> list[str]:
    sources: list[str] = []
    for tag in soup.find_all(True):
        src = str(tag.get("src") or "").strip()
        if src and not _is_ignorable_source(src):
            sources.append(src)
        srcset = str(tag.get("srcset") or "").strip()
        if srcset:
            sources.extend(_srcset_sources(srcset))
        style = str(tag.get("style") or "")
        for match in _CSS_URL_PATTERN.finditer(style):
            source = match.group(2).strip()
            if source and not _is_ignorable_source(source):
                sources.append(source)
    return sources


def _replace_srcset(value: str, replacements: dict[str, str]) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end, source in _srcset_source_spans(value):
        replacement = replacements.get(source)
        if not replacement:
            continue
        parts.append(value[cursor:start])
        parts.append(replacement)
        cursor = end
    if not parts:
        return value
    parts.append(value[cursor:])
    return "".join(parts)


def _replace_css_urls(value: str, replacements: dict[str, str]) -> str:
    def replace_url(match: re.Match[str]) -> str:
        source = match.group(2).strip()
        replacement = replacements.get(source)
        if not replacement:
            return match.group(0)
        quote = match.group(1)
        return f"url({quote}{replacement}{quote})"

    return _CSS_URL_PATTERN.sub(replace_url, value)


def _apply_replacements(soup: BeautifulSoup, replacements: dict[str, str]) -> None:
    for tag in soup.find_all(True):
        src = str(tag.get("src") or "").strip()
        if src in replacements:
            tag["src"] = replacements[src]
        srcset = str(tag.get("srcset") or "")
        if srcset:
            tag["srcset"] = _replace_srcset(srcset, replacements)
        style = str(tag.get("style") or "")
        if style:
            tag["style"] = _replace_css_urls(style, replacements)


async def localize_html_images(
    html: str,
    *,
    load_image: ImageLoader,
    store_image: ImageStorer,
    cleanup_image: ImageCleaner,
    is_local_source: LocalSourcePredicate,
    max_images: int,
    max_total_bytes: int,
    fetch_concurrency: int = 3,
) -> ImageLocalizationResult:
    """Copy every non-local image reference and return the rewritten HTML.

    Downloads finish before any object is persisted. If persistence itself fails,
    all objects created during this call are deleted before the error is exposed.
    """
    soup = BeautifulSoup(html, "html.parser")
    sources = _collect_sources(soup)
    candidates = list(dict.fromkeys(source for source in sources if not is_local_source(source)))
    if len(candidates) > max_images:
        raise ImageLocalizationError(f"内容最多包含 {max_images} 张图片")
    if not candidates:
        return ImageLocalizationResult(html=html, localized_count=0, replacements={})

    semaphore = asyncio.Semaphore(fetch_concurrency)
    timeout = httpx.Timeout(10.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        async def fetch(source: str) -> tuple[str, bytes, local_uploads.ImageInfo]:
            async with semaphore:
                data, image = await load_image(source, client)
            return source, data, image

        try:
            fetched = await asyncio.gather(*(fetch(source) for source in candidates))
        except ImageLocalizationError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapters return provider-specific errors.
            raise ImageLocalizationError(str(exc) or "图片下载失败") from exc

    total_size = sum(len(data) for _, data, _ in fetched)
    if total_size > max_total_bytes:
        raise ImageLocalizationError(f"图片总大小超过 {max_total_bytes // (1024 * 1024)}MB 限制")

    stored: list[StoredImage] = []
    replacements: dict[str, str] = {}
    try:
        for source, data, image in fetched:
            persisted = store_image(data, image, source)
            stored.append(persisted)
            replacements[source] = persisted.url
    except Exception as exc:  # noqa: BLE001 - preserve all-or-nothing caller semantics.
        for persisted in reversed(stored):
            try:
                cleanup_image(persisted)
            except Exception:
                continue
        if isinstance(exc, ImageLocalizationError):
            raise
        raise ImageLocalizationError(str(exc) or "图片保存失败") from exc

    _apply_replacements(soup, replacements)
    return ImageLocalizationResult(
        html="".join(str(node) for node in soup.contents).strip(),
        localized_count=len(replacements),
        replacements=replacements,
        stored_images=tuple(stored),
    )
