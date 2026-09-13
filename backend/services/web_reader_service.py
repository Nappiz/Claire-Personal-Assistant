"""Bounded page reading through Jina Reader for URLs discovered this turn."""

import re
from datetime import datetime, timezone

import httpx

from configs.settings import settings
from schemas.chat_sch import WebPageContent
from services.web_search_service import normalize_public_url


class WebReadRejectedError(ValueError):
    """The requested URL was not a public URL returned by web search."""


def _bounded_markdown(value: str, limit: int) -> str:
    cleaned = str(value or "").replace("\x00", "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned

    suffix = "\n\n[Content truncated by Claire's web reader]"
    candidate = cleaned[: limit - len(suffix)]
    paragraph_end = candidate.rfind("\n\n")
    if paragraph_end >= int(len(candidate) * 0.7):
        candidate = candidate[:paragraph_end]
    return candidate.rstrip() + suffix


async def read_url(
    url: str,
    *,
    allowed_urls: set[str],
    title: str = "",
) -> WebPageContent:
    """Read one allowlisted public page as clean, bounded Markdown."""
    normalized_url = normalize_public_url(url)
    normalized_allowlist = {
        normalized
        for candidate in allowed_urls
        if (normalized := normalize_public_url(candidate)) is not None
    }
    if not normalized_url or normalized_url not in normalized_allowlist:
        raise WebReadRejectedError("read_url only accepts URLs returned by web_search in this turn")

    max_chars = max(1000, min(int(settings.WEB_READ_MAX_CHARS), 10_000))
    timeout_seconds = max(2.0, min(float(settings.WEB_READ_TIMEOUT_SECONDS), 30.0))
    reader_endpoint = f"{settings.JINA_READER_URL.rstrip('/')}/{normalized_url}"
    headers = {
        "Accept": "text/markdown",
        "DNT": "1",
        "X-Locale": "id-ID",
    }
    if settings.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.JINA_API_KEY}"

    chunks: list[str] = []
    received_chars = 0
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with client.stream("GET", reader_endpoint, headers=headers) as response:
            response.raise_for_status()
            async for chunk in response.aiter_text():
                if not chunk:
                    continue
                remaining = max_chars + 1000 - received_chars
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                received_chars += min(len(chunk), remaining)

    content = _bounded_markdown("".join(chunks), max_chars)
    if not content:
        raise ValueError("Jina Reader returned an empty page")
    return WebPageContent(
        title=title,
        url=normalized_url,
        content=content,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
