import re
from dataclasses import dataclass
from typing import Literal

_EXPLICIT_SEARCH_RE = re.compile(
    r"\b(?:cari(?:kan)?|google(?:kan)?|googling|internet|browsing|web\s+search|search\s+(?:web|internet))\b",
    re.IGNORECASE,
)
_LIVE_FACT_RE = re.compile(
    r"\b(?:harga|tarif|kurs|cuaca|berita|price|prices|weather|exchange\s+rate|"
    r"terbaru|terkini|sekarang|skrg|saat\s+ini|hari\s+ini|latest|current|today|"
    r"masih\s+beroperasi|status\s+operasional)\b", re.IGNORECASE,
)


def explicit_search_requested(message: str) -> bool:
    return bool(_EXPLICIT_SEARCH_RE.search(str(message or "")))


def requires_web_search(message: str) -> bool:
    return explicit_search_requested(message) or bool(_LIVE_FACT_RE.search(str(message or "")))


def canonical_search_query(message: str) -> str:
    query = " ".join(str(message or "").split())
    query = re.sub(r"^(?:(?:oke|nah|ya|tolong|please|aku|saya|kamu|bisa|boleh|minta|"
                   r"suruh|coba|lebih|strict|lagi|dong|chat|claire)\b[\s,]*)+", "", query, flags=re.I)
    query = re.sub(r"^(?:cari(?:kan)?|google(?:kan)?|googling|search)(?:\s+(?:di|lewat|"
                   r"melalui|pakai|gunakan)\s+(?:internet|web|google))?\s*", "", query, flags=re.I)
    query = re.sub(r"\s+(?:(?:di|lewat|melalui|dari)\s+)?(?:internet|google|web)"
                   r"(?:\s+(?:dong|ya|sekarang))?[.!?]*$", "", query, flags=re.I)
    return query.strip(" ,.!?")[:300]

@dataclass(frozen=True)
class WebSearchPlan:
    needed: bool
    query: str = ""
    queries: tuple[str, ...] = ()
    time_range: Literal["day", "month", "year"] | None = None
    reason: str = "not_needed"
    research_goal: str = ""


def plan_web_search(user_message: str) -> WebSearchPlan:
    """Bounded fallback for explicit search and potentially changing public facts."""
    normalized = " ".join(str(user_message or "").split())
    if not normalized:
        return WebSearchPlan(False, reason="empty")
    if not requires_web_search(normalized):
        return WebSearchPlan(False, reason="explicit_search_not_requested")
    query = canonical_search_query(normalized)
    if not query:
        return WebSearchPlan(False, reason="missing_search_target")
    return WebSearchPlan(
        True,
        query=query,
        queries=(query,),
        reason="explicit_search_fallback" if explicit_search_requested(normalized) else "live_fact_required",
        research_goal=query,
    )


def plan_web_search_with_context(
    user_message: str,
    session_history: list | None = None,
) -> WebSearchPlan:
    """Compatibility wrapper for the explicit-only deterministic fallback."""
    del session_history
    return plan_web_search(user_message)
