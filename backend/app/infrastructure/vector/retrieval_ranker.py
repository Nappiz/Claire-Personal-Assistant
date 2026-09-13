from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from configs.settings import settings
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, IsEmptyCondition
from . import state

from . import qdrant_client_factory
from . import embedding_encoder
_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)

def _lexical_overlap(query: str, content: str) -> float:
    query_tokens = {token.lower() for token in _TOKEN_RE.findall(query) if len(token) > 2}
    content_tokens = {token.lower() for token in _TOKEN_RE.findall(content) if len(token) > 2}
    if not query_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)

def _recency_score(stored_at: object) -> float:
    if not stored_at:
        return 0.5
    try:
        parsed = datetime.fromisoformat(str(stored_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max((datetime.now(timezone.utc) - parsed).total_seconds(), 0.0) / 86400
        return 0.5 ** (age_days / 365.0)
    except (TypeError, ValueError):
        return 0.5

def search_memory(query: str, limit: int = 3, *, project_id: str | None = None) -> list[dict]:
    """Search approved user memories above the configured relevance threshold."""
    safe_limit = min(max(int(limit), 1), 20)
    active_project_id = str(project_id or "").strip() or None
    scope_conditions = [
        FieldCondition(key="scope", match=MatchValue(value="global")),
        # Vectors written before scoped memory existed are global memories.
        IsEmptyCondition(is_empty={"key": "scope"}),
    ]
    if active_project_id:
        scope_conditions.insert(
            0,
            FieldCondition(key="project_id", match=MatchValue(value=active_project_id)),
        )
    search_result = qdrant_client_factory._get_client().query_points(
        collection_name=state.COLLECTION_NAME,
        query=embedding_encoder.embed_text(query, purpose="query"),
        query_filter=Filter(
            must=[
                FieldCondition(key="source_role", match=MatchValue(value="user")),
                FieldCondition(key="epistemic_status", match=MatchValue(value="user_assertion")),
                FieldCondition(key="evidence_version", match=MatchValue(value=2)),
                FieldCondition(key="embedding_signature", match=MatchValue(value=embedding_encoder.embedding_signature())),
            ],
            must_not=[
                FieldCondition(key="memory_status", match=MatchValue(value="inactive")),
            ],
            should=scope_conditions,
        ),
        score_threshold=float(settings.MEMORY_SEARCH_SCORE_THRESHOLD),
        # Multiple chunks can belong to one source message. Fetch enough
        # candidates to preserve result diversity before message-level dedupe.
        limit=min(safe_limit * 8, 100),
        with_payload=True,
    )

    ranked: list[tuple[float, dict]] = []
    for hit in search_result.points:
        payload = dict(hit.payload or {})
        content = str(payload.get("text") or "").strip()
        if not content:
            continue
        semantic_score = max(-1.0, min(1.0, float(hit.score)))
        # Semantic relevance remains dominant. The remaining signals resolve
        # close matches without allowing a recent but irrelevant item through
        # the hard vector threshold above.
        rank_score = (
            (semantic_score * 0.78)
            + (_lexical_overlap(query, content) * 0.10)
            + (_recency_score(payload.get("stored_at")) * 0.03)
            + 0.05  # fixed trust score: the query filter guarantees user authorship
            + (0.04 if active_project_id and payload.get("project_id") == active_project_id else 0.0)
        )
        ranked.append(
            (
                rank_score,
                {
                    "content": content,
                    "score": semantic_score,
                    "source_role": "user",
                    "epistemic_status": "user_assertion",
                    "session_id": payload.get("session_id"),
                    "message_id": payload.get("message_id"),
                    "event_id": payload.get("event_id"),
                    "chunk_index": payload.get("chunk_index"),
                    "chunk_count": payload.get("chunk_count"),
                    "span_start": payload.get("span_start"),
                    "span_end": payload.get("span_end"),
                    "stored_at": payload.get("stored_at"),
                    "project_id": payload.get("project_id"),
                    "scope": "project" if payload.get("project_id") else "global",
                    "memory_status": str(payload.get("memory_status") or "active"),
                },
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    unique: list[dict] = []
    seen_sources: set[str] = set()
    for _, memory in ranked:
        source_key = str(
            memory.get("message_id")
            or memory.get("event_id")
            or f"legacy:{memory.get('content')}"
        )
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        unique.append(memory)
        if len(unique) >= safe_limit:
            break
    return unique

def search_project_memory_candidates(query: str, limit: int = 12) -> list[dict]:
    """Search project-scoped memories solely to resolve an ambiguous project reference."""
    safe_limit = min(max(int(limit), 1), 30)
    search_result = qdrant_client_factory._get_client().query_points(
        collection_name=state.COLLECTION_NAME,
        query=embedding_encoder.embed_text(query, purpose="query"),
        query_filter=Filter(
            must=[
                FieldCondition(key="source_role", match=MatchValue(value="user")),
                FieldCondition(key="epistemic_status", match=MatchValue(value="user_assertion")),
                FieldCondition(key="evidence_version", match=MatchValue(value=2)),
                FieldCondition(key="scope", match=MatchValue(value="project")),
                FieldCondition(key="embedding_signature", match=MatchValue(value=embedding_encoder.embedding_signature())),
            ],
            must_not=[
                FieldCondition(key="memory_status", match=MatchValue(value="inactive")),
            ],
        ),
        score_threshold=float(settings.MEMORY_SEARCH_SCORE_THRESHOLD),
        limit=safe_limit,
        with_payload=True,
    )
    candidates = []
    for hit in search_result.points:
        payload = dict(hit.payload or {})
        project_id = str(payload.get("project_id") or "").strip()
        content = str(payload.get("text") or "").strip()
        if not project_id or not content:
            continue
        candidates.append(
            {
                "project_id": project_id,
                "content": content,
                "score": max(-1.0, min(1.0, float(hit.score))),
            }
        )
    return candidates
