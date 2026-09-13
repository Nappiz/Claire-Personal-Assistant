import asyncio
import html
import ipaddress
import logging
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from configs.settings import settings
from schemas.chat_sch import WebSearchContext, WebSearchResult

logger = logging.getLogger(__name__)

_SEARCH_ENGINES = "google"
_ALLOWED_ENGINE_NAMES = frozenset(_SEARCH_ENGINES.split(","))
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) "
    "Gecko/20100101 Firefox/142.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.6 Safari/605.1.15",
)

_EXPLICIT_SEARCH_RE = re.compile(
    r"\b(?:cari(?:kan)?|google(?:kan)?|googling)\b",
    re.IGNORECASE,
)
_TFIDF_TOKEN_RE = re.compile(r"[\w.+-]+", re.UNICODE)
_TFIDF_STOPWORDS = frozenset(
    {
        "a", "an", "and", "atau", "cari", "carikan", "dan", "dari", "di",
        "google", "googlekan", "googling", "ini", "itu", "ke", "of", "on",
        "pada", "the", "to", "untuk", "yang",
    }
)


@dataclass(frozen=True)
class WebSearchPlan:
    needed: bool
    query: str = ""
    queries: tuple[str, ...] = ()
    time_range: Literal["day", "month", "year"] | None = None
    reason: str = "not_needed"
    research_goal: str = ""


def plan_web_search(user_message: str) -> WebSearchPlan:
    """Fallback only for an explicit request to search or Google something."""
    normalized = " ".join(str(user_message or "").split())
    if not normalized:
        return WebSearchPlan(False, reason="empty")
    if not _EXPLICIT_SEARCH_RE.search(normalized):
        return WebSearchPlan(False, reason="explicit_search_not_requested")
    query = normalized[:400]
    return WebSearchPlan(
        True,
        query=query,
        queries=(query,),
        reason="explicit_search_fallback",
    )


def plan_web_search_with_context(
    user_message: str,
    session_history: list | None = None,
) -> WebSearchPlan:
    """Compatibility wrapper for the explicit-only deterministic fallback."""
    del session_history
    return plan_web_search(user_message)


def _clean_text(value: object, *, limit: int) -> str:
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    return " ".join(text.split())[:limit]


def normalize_public_url(value: object) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        return None

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))[:2048]


def _tfidf_terms(value: str) -> list[str]:
    """Return generic word and adjacent-word features without domain knowledge."""
    words = [
        token.lower()
        for token in _TFIDF_TOKEN_RE.findall(value)
        if len(token) >= 2 and token.lower() not in _TFIDF_STOPWORDS
    ]
    bigrams = [f"{left}::{right}" for left, right in zip(words, words[1:])]
    return words + bigrams


def _rank_results_by_tfidf(
    results: list[WebSearchResult],
    query: str,
) -> list[WebSearchResult]:
    """Rank search snippets by cosine similarity in a small local TF-IDF corpus."""
    query_terms = _tfidf_terms(query)
    if not results or not query_terms:
        return results

    document_terms = [
        _tfidf_terms(f"{result.title} {result.snippet}")
        for result in results
    ]
    document_frequency: Counter[str] = Counter()
    for terms in document_terms:
        document_frequency.update(set(terms))

    document_count = len(document_terms)

    def vectorize(terms: list[str]) -> dict[str, float]:
        if not terms:
            return {}
        counts = Counter(terms)
        term_count = len(terms)
        return {
            term: (count / term_count)
            * (math.log((document_count + 1) / (document_frequency.get(term, 0) + 1)) + 1.0)
            for term, count in counts.items()
        }

    def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot_product = sum(weight * right.get(term, 0.0) for term, weight in left.items())
        if dot_product <= 0.0:
            return 0.0
        left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
        right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
        return dot_product / (left_norm * right_norm) if left_norm and right_norm else 0.0

    query_vector = vectorize(query_terms)
    ranked: list[tuple[float, int, WebSearchResult]] = []
    for index, (result, terms) in enumerate(zip(results, document_terms)):
        similarity = cosine_similarity(query_vector, vectorize(terms))
        # Lexical overlap is a ranking signal, not a relevance requirement:
        # translations and synonyms can have zero overlap with the goal.
        ranked.append((similarity, index, result))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [result for _, _, result in ranked]


def _parse_results(payload: object, *, limit: int, query: str = "") -> list[WebSearchResult]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("SearXNG returned an invalid JSON schema")

    parsed_results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        url = normalize_public_url(item.get("url"))
        title = _clean_text(item.get("title"), limit=300)
        if not url or not title or url in seen_urls:
            continue

        raw_engines = item.get("engines")
        if isinstance(raw_engines, list):
            engine_names = [
                _clean_text(name, limit=40).lower()
                for name in raw_engines[:3]
                if _clean_text(name, limit=40).lower() in _ALLOWED_ENGINE_NAMES
            ]
        else:
            raw_engine = _clean_text(item.get("engine"), limit=80).lower()
            engine_names = [raw_engine] if raw_engine in _ALLOWED_ENGINE_NAMES else []
        if not engine_names:
            continue
        engine = ", ".join(engine_names)
        published_at = _clean_text(
            item.get("publishedDate") or item.get("published_date"),
            limit=80,
        ) or None
        parsed_results.append(
            WebSearchResult(
                title=title,
                url=url,
                snippet=_clean_text(item.get("content"), limit=1200),
                engine=engine,
                published_at=published_at,
            )
        )
        seen_urls.add(url)
        if len(parsed_results) >= 60:
            break
    if query:
        parsed_results = _rank_results_by_tfidf(parsed_results, query)
    return parsed_results[:limit]


def _merge_result_groups(
    groups: list[list[WebSearchResult]],
    *,
    limit: int,
) -> list[WebSearchResult]:
    """Round-robin result groups so every generated query is represented."""
    merged: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    max_group_length = max((len(group) for group in groups), default=0)
    for index in range(max_group_length):
        for group in groups:
            if index >= len(group):
                continue
            result = group[index]
            if result.url in seen_urls:
                continue
            merged.append(result)
            seen_urls.add(result.url)
            if len(merged) >= limit:
                return merged
    return merged


async def retrieve_web_context(
    user_message: str,
    session_history: list | None = None,
    *,
    plan: WebSearchPlan | None = None,
    raise_on_error: bool = False,
) -> WebSearchContext:
    """Fetch bounded live-search context, optionally surfacing degraded searches."""
    plan = plan or plan_web_search_with_context(user_message, session_history)
    if not plan.needed:
        return WebSearchContext(status="not_needed")
    if not settings.WEB_SEARCH_ENABLED:
        return WebSearchContext(status="disabled", query=plan.query)

    searched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    timeout_seconds = max(0.5, min(float(settings.WEB_SEARCH_TIMEOUT_SECONDS), 10.0))
    max_results = max(1, min(int(settings.WEB_SEARCH_MAX_RESULTS), 10))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": random.choice(_USER_AGENTS),
            },
        ) as client:
            async def fetch_query(search_query: str) -> list[WebSearchResult]:
                params = {
                    "q": search_query,
                    "format": "json",
                    "engines": _SEARCH_ENGINES,
                    "language": "id-ID",
                    "safesearch": "1",
                    "categories": "general",
                }
                if plan.time_range:
                    params["time_range"] = plan.time_range
                response = await client.get(
                    f"{settings.SEARXNG_URL.rstrip('/')}/search",
                    params=params,
                )
                response.raise_for_status()
                return _parse_results(
                    response.json(),
                    limit=max_results,
                    query=search_query,
                )

            planned_queries = plan.queries or (plan.query,)
            search_queries: list[str] = []
            for planned_query in planned_queries:
                search_query = " ".join(str(planned_query or "").split())[:300]
                if search_query and search_query not in search_queries:
                    search_queries.append(search_query)
                if len(search_queries) >= 3:
                    break
            outcomes = await asyncio.gather(
                *(fetch_query(search_query) for search_query in search_queries),
                return_exceptions=True,
            )
            result_groups = [outcome for outcome in outcomes if isinstance(outcome, list)]
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            if failures and not result_groups:
                raise failures[0]
            for failure in failures:
                if isinstance(failure, asyncio.CancelledError):
                    raise failure

            # Rank across every query result against the resolved research goal,
            # not merely the first query. This matters for conversational
            # follow-ups where an earlier entity is only a comparison baseline.
            candidate_limit = max_results * max(len(result_groups), 1)
            candidates = _merge_result_groups(result_groups, limit=candidate_limit)
            ranked = _rank_results_by_tfidf(
                candidates,
                plan.research_goal or plan.query,
            )
            # Keep a representative from each successful query before filling
            # the remaining budget by goal relevance. A translated query must
            # not disappear merely because another query shares more words.
            representatives = _merge_result_groups(
                [group[:1] for group in result_groups], limit=max_results
            ) if max_results >= sum(bool(group) for group in result_groups) else []
            reserved_urls = {result.url for result in representatives}
            selected_urls = reserved_urls | {
                result.url for result in [
                    result for result in ranked if result.url not in reserved_urls
                ][:max_results - len(representatives)]
            }
            results = [result for result in ranked if result.url in selected_urls]
            if not results:
                return WebSearchContext(
                    status="no_results",
                    query=plan.query,
                    searched_at=searched_at,
                    warnings=["web_search_returned_no_results"] + (
                        ["web_search_partial_failure"] if failures else []
                    ),
                )
            return WebSearchContext(
                status="ok",
                query=plan.query,
                searched_at=searched_at,
                results=results,
                warnings=["web_search_partial_failure"] if failures else [],
            )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("SearXNG search failed for %r: %s", plan.query, exc)
        if raise_on_error:
            raise
        return WebSearchContext(
            status="unavailable",
            query=plan.query,
            searched_at=searched_at,
            warnings=["web_search_unavailable"],
        )
