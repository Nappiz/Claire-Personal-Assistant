import html
import re
from schemas.chat_sch import WebSearchResult
from app.domain.web.url_policy import normalize_public_url
from app.domain.web.ranking import rank_results_by_tfidf

_SEARCH_ENGINES = "google"
_ALLOWED_ENGINE_NAMES = frozenset(_SEARCH_ENGINES.split(","))

def clean_text(value: object, *, limit: int) -> str:
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    return " ".join(text.split())[:limit]


def parse_results(payload: object, *, limit: int, query: str = "") -> list[WebSearchResult]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("SearXNG returned an invalid JSON schema")

    parsed_results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        url = normalize_public_url(item.get("url"))
        title = clean_text(item.get("title"), limit=300)
        if not url or not title or url in seen_urls:
            continue

        raw_engines = item.get("engines")
        if isinstance(raw_engines, list):
            engine_names = [
                clean_text(name, limit=40).lower()
                for name in raw_engines[:3]
                if clean_text(name, limit=40).lower() in _ALLOWED_ENGINE_NAMES
            ]
        else:
            raw_engine = clean_text(item.get("engine"), limit=80).lower()
            engine_names = [raw_engine] if raw_engine in _ALLOWED_ENGINE_NAMES else []
        if not engine_names:
            continue
        engine = ", ".join(engine_names)
        published_at = clean_text(
            item.get("publishedDate") or item.get("published_date"),
            limit=80,
        ) or None
        parsed_results.append(
            WebSearchResult(
                title=title,
                url=url,
                snippet=clean_text(item.get("content"), limit=1200),
                engine=engine,
                published_at=published_at,
            )
        )
        seen_urls.add(url)
        if len(parsed_results) >= 60:
            break
    if query:
        parsed_results = rank_results_by_tfidf(parsed_results, query)
    return parsed_results[:limit]
