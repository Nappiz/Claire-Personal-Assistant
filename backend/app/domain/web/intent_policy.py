import re
from dataclasses import dataclass
from typing import Literal

_EXPLICIT_SEARCH_RE = re.compile(
    r"\b(?:cari(?:kan)?|google(?:kan)?|googling)\b",
    re.IGNORECASE,
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
