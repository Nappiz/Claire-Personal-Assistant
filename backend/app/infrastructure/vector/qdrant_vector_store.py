from __future__ import annotations
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal
from configs.settings import settings
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, PointStruct, HasIdCondition
from . import state

logger = logging.getLogger(__name__)
from . import qdrant_client_factory
from . import embedding_encoder
from . import chunker
from . import retrieval_ranker, vector_maintenance

def _write_memory(
    text: str,
    metadata: dict | None = None,
    dedup_key: str | None = None,
    point_id: str | None = None,
    *,
    only_if_changed: bool = False,
) -> tuple[str, bool]:
    """Index all token-bounded chunks of one assertion event idempotently."""
    metadata = dict(metadata or {})
    source_role = str(metadata.get("source_role") or "user").lower()
    if source_role != "user":
        raise ValueError("Vector memory accepts user-authored content only")
    if str(metadata.get("epistemic_status") or "") != "user_assertion":
        raise ValueError("Vector memory requires an explicit user_assertion classification")
    assertion_spans = metadata.get("assertion_spans")
    if not isinstance(assertion_spans, list) or not assertion_spans:
        raise ValueError("Vector memory requires validated assertion spans")
    if any(
        not isinstance(span, dict)
        or span.get("modality") != "asserted_fact"
        or span.get("polarity") != "positive"
        or not str(span.get("text") or "").strip()
        for span in assertion_spans
    ):
        raise ValueError("Vector memory assertion spans have an invalid evidence classification")
    clean_text = " ".join(str(text or "").split())
    if not clean_text:
        raise ValueError("Cannot persist empty vector memory")
    evidence_ranges = []
    evidence_cursor = 0
    for span in assertion_spans:
        span_text = " ".join(str(span["text"]).split())
        span_start = clean_text.find(span_text, evidence_cursor)
        if span_start < 0:
            raise ValueError("Assertion evidence text must be present in the indexed memory")
        span_end = span_start + len(span_text)
        evidence_ranges.append((span_start, span_end, span))
        evidence_cursor = span_end
    metadata.pop("assertion_spans", None)

    event_id = point_id or str(uuid.uuid4())
    project_id = str(metadata.get("project_id") or "").strip() or None
    metadata["project_id"] = project_id
    metadata["scope"] = "project" if project_id else "global"
    stored_at = metadata.get("stored_at") or datetime.now(timezone.utc).isoformat()
    metadata.update({
        "event_id": event_id,
        "source_role": "user",
        "epistemic_status": "user_assertion",
        "evidence_version": 2,
        "memory_status": str(metadata.get("memory_status") or "active"),
        "stored_at": str(stored_at),
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
        "embedding_signature": embedding_encoder.embedding_signature(),
        "interaction_fingerprint": hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
    })
    if dedup_key:
        metadata["legacy_dedup_key"] = dedup_key

    chunk_offsets = chunker._memory_chunk_offsets(clean_text)
    chunk_payloads: list[tuple[str, dict]] = []
    for chunk_index, (start, end) in enumerate(chunk_offsets):
        raw_chunk = clean_text[start:end]
        leading = len(raw_chunk) - len(raw_chunk.lstrip())
        trailing = len(raw_chunk) - len(raw_chunk.rstrip())
        start += leading
        end -= trailing
        chunk_text = clean_text[start:end]
        if not chunk_text:
            continue
        payload = dict(metadata)
        payload.update({
            "text": chunk_text,
            "assertion_spans": [
                {
                    **span,
                    "text": clean_text[max(start, evidence_start):min(end, evidence_end)],
                    "span_start": max(start, evidence_start),
                    "span_end": min(end, evidence_end),
                }
                for evidence_start, evidence_end, span in evidence_ranges
                if evidence_start < end and evidence_end > start
            ],
            "chunk_index": chunk_index,
            "chunk_count": len(chunk_offsets),
            "span_start": start,
            "span_end": end,
        })
        payload["projection_fingerprint"] = hashlib.sha256(json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        chunk_payloads.append((chunk_text, payload))
    if not chunk_payloads:
        raise ValueError("Cannot persist empty vector memory")
    expected_ids = [chunker._chunk_point_id(event_id, index) for index in range(len(chunk_payloads))]
    qdrant = qdrant_client_factory._get_client()
    if only_if_changed:
        existing = {}
        # Keep point reads bounded even for a very large assertion document.
        for start in range(0, len(expected_ids), 64):
            existing.update({str(point.id): point for point in qdrant.retrieve(
                collection_name=state.COLLECTION_NAME, ids=expected_ids[start:start + 64],
                with_payload=True, with_vectors=False,
            )})
        current = all(
            str(point_id) in existing
            and all((existing[str(point_id)].payload or {}).get(key) == value
                    for key, value in payload.items())
            for point_id, (_, payload) in zip(expected_ids, chunk_payloads)
        )
        if current:
            qdrant.delete(collection_name=state.COLLECTION_NAME, points_selector=Filter(
                must=[FieldCondition(key="event_id", match=MatchValue(value=event_id))],
                must_not=[HasIdCondition(has_id=expected_ids)],
            ))
            return event_id, False
    if len(chunk_payloads) == 1:
        vectors = [embedding_encoder.embed_text(chunk_payloads[0][0], purpose="passage")]
    else:
        vectors = embedding_encoder.embed_texts([item[0] for item in chunk_payloads], purpose="passage")
    if len(vectors) != len(chunk_payloads):
        raise embedding_encoder.EmbeddingUnavailableError("Embedding model returned an incomplete chunk batch")
    points = [
        PointStruct(
            id=chunker._chunk_point_id(event_id, chunk_index),
            vector=vector,
            payload=payload,
        )
        for chunk_index, ((_, payload), vector) in enumerate(zip(chunk_payloads, vectors))
    ]
    qdrant.upsert(
        collection_name=state.COLLECTION_NAME,
        points=points,
    )
    if only_if_changed:
        # Remove obsolete chunks of this event after the new projection is
        # durable. Other events are not deleted by a count-based assumption.
        qdrant.delete(collection_name=state.COLLECTION_NAME, points_selector=Filter(
            must=[FieldCondition(key="event_id", match=MatchValue(value=event_id))],
            must_not=[HasIdCondition(has_id=expected_ids)],
        ))
    logger.info("Saved user memory %s to Qdrant in %d chunks", event_id, len(points))
    return event_id, True

def save_memory(text: str, metadata: dict | None = None, dedup_key: str | None = None,
                point_id: str | None = None) -> str:
    return _write_memory(text, metadata, dedup_key, point_id)[0]

def reconcile_memory(text: str, metadata: dict, *, point_id: str) -> bool:
    """Repair missing/stale event chunks; validated projections skip embedding."""
    return _write_memory(text, metadata, point_id=point_id, only_if_changed=True)[1]

def set_memories_status(
    message_ids: list[str],
    *,
    status: Literal["active", "inactive"],
    superseded_by: str | None = None,
    event_at: datetime | None = None,
) -> int:
    """Propagate graph lifecycle decisions into vector-memory payloads."""
    clean_ids = sorted({str(item).strip() for item in message_ids if str(item).strip()})
    if not clean_ids:
        return 0
    payload = {
        "memory_status": status,
        "memory_status_updated_at": (event_at or datetime.now(timezone.utc)).isoformat(),
    }
    if superseded_by:
        payload["superseded_by"] = str(superseded_by)
    qdrant = qdrant_client_factory._get_client()
    for message_id in clean_ids:
        qdrant.set_payload(
            collection_name=state.COLLECTION_NAME,
            payload=payload,
            points=Filter(
                must=[FieldCondition(key="message_id", match=MatchValue(value=message_id))]
            ),
        )
    return len(clean_ids)

def resolve_entity(name: str) -> str:
    """Compatibility shim; contextual entity resolution belongs to Neo4j."""
    return name.strip().lower()

def delete_memory_by_session(session_id: str) -> None:
    selector = Filter(
        must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
    )
    errors: list[Exception] = []
    collection_names = tuple(dict.fromkeys((state.COLLECTION_NAME, state.LEGACY_COLLECTION_NAME)))
    qdrant = qdrant_client_factory._get_client()
    for collection_name in collection_names:
        try:
            qdrant.get_collection(collection_name=collection_name)
            qdrant.delete(collection_name=collection_name, points_selector=selector)
        except Exception as exc:
            errors.append(exc)
            logger.warning("Could not delete session vectors from %s: %s", collection_name, exc)
    if len(errors) == len(collection_names):
        raise RuntimeError(f"Qdrant session deletion failed: {errors[-1]}")

class QdrantVectorStore:
    """Concrete implementation of the VectorStore port."""
    def save_memory(self, text: str, metadata: dict | None = None, dedup_key: str | None = None, point_id: str | None = None) -> str:
        return save_memory(text, metadata, dedup_key, point_id)

    def reconcile_memory(self, text: str, metadata: dict, *, point_id: str) -> bool:
        return reconcile_memory(text, metadata, point_id=point_id)

    def search_memory(self, query: str, limit: int = 3, *, project_id: str | None = None) -> list[dict]:
        return retrieval_ranker.search_memory(query, limit, project_id=project_id)

    def search_project_memory_candidates(self, query: str, limit: int = 12) -> list[dict]:
        return retrieval_ranker.search_project_memory_candidates(query, limit)

    def set_memories_status(self, *args, **kwargs) -> int:
        # Preserve legacy call shapes, including patched compensation callbacks.
        # The implementation remains the single owner of argument validation.
        return set_memories_status(*args, **kwargs)

    def delete_memory_by_session(self, session_id: str) -> None:
        return delete_memory_by_session(session_id)

    def get_stats(self) -> dict:
        return vector_maintenance.get_stats()

    def warmup_embedding_model(self, *, force_retry: bool = False) -> dict:
        return vector_maintenance.warmup_embedding_model(force_retry=force_retry)

    def embedding_signature(self) -> str:
        return embedding_encoder.embedding_signature()


vector_store = QdrantVectorStore()
