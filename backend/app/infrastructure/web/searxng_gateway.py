import asyncio
import logging
import random
from datetime import datetime, timezone
import httpx
from configs.settings import settings
from schemas.chat_sch import WebSearchContext, WebSearchResult
from app.domain.web.intent_policy import WebSearchPlan, plan_web_search_with_context
from app.domain.web.ranking import rank_results_by_tfidf, merge_result_groups
from app.domain.web.evidence_policy import filter_search_evidence
from app.infrastructure.web.search_results import parse_results

logger = logging.getLogger("services.web_search_service")
from app.infrastructure.web.search_config import SEARCH_ENGINES as _SEARCH_ENGINES, USER_AGENTS as _USER_AGENTS

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
                payload = response.json()
                candidates = parse_results(
                    payload,
                    limit=60,
                    query=search_query,
                )
                # Validate against the query that actually retrieved the result,
                # not only the (possibly differently worded) research goal.
                relevant = filter_search_evidence(candidates, search_query)[:max_results]
                if not relevant and payload.get("unresponsive_engines"):
                    # SearXNG can return HTTP 200 even when Google is suspended
                    # by CAPTCHA. That is an engine failure, not an empty search.
                    raise ValueError("SearXNG search engine unavailable")
                return relevant

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
            candidates = merge_result_groups(result_groups, limit=candidate_limit)
            ranked = rank_results_by_tfidf(
                candidates,
                plan.research_goal or plan.query,
            )
            # Keep a representative from each successful query before filling
            # the remaining budget by goal relevance. A translated query must
            # not disappear merely because another query shares more words.
            representatives = merge_result_groups(
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
