"""Vector-memory storage backed by a local Qdrant database.

Only user-authored assertions are indexed. Assistant responses are deliberately
excluded because generated text is not authoritative evidence about Nafiz.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    IsEmptyCondition,
    PointStruct,
    HasIdCondition,
    VectorParams,
)

from configs.settings import settings


logger = logging.getLogger(__name__)

if settings.HF_TOKEN:
    os.environ["HF_TOKEN"] = settings.HF_TOKEN
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from sentence_transformers import SentenceTransformer  # noqa: E402


class EmbeddingUnavailableError(RuntimeError):
    """Raised when a real semantic embedding cannot be produced safely."""


COLLECTION_NAME = settings.QDRANT_MEMORY_COLLECTION
LEGACY_COLLECTION_NAME = "personia_memory"

encoder = None
VECTOR_SIZE = 0
_encoder_error: str | None = None
_encoder_load_attempted = False
_encoder_failure_count = 0
_encoder_next_retry_at = 0.0
_pending_encoder = None
_encoder_lock = threading.Lock()

client = None
_client_error: str | None = None
_client_lock = threading.Lock()


def _get_client():
    global client, _client_error
    if client is not None:
        return client
    with _client_lock:
        if client is not None:
            return client
        try:
            client = QdrantClient(path=settings.QDRANT_PATH)
            _client_error = None
            return client
        except Exception as exc:
            _client_error = str(exc)
            raise RuntimeError(f"Qdrant is unavailable: {exc}") from exc


def _ensure_collection(collection_name: str) -> None:
    if VECTOR_SIZE <= 0:
        return
    qdrant = _get_client()
    try:
        collection = qdrant.get_collection(collection_name=collection_name)
    except Exception:
        logger.info("Creating Qdrant collection %s (%s dimensions)", collection_name, VECTOR_SIZE)
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        return

    configured_size = getattr(getattr(collection.config.params, "vectors", None), "size", None)
    if configured_size is not None and int(configured_size) != VECTOR_SIZE:
        raise RuntimeError(
            f"Qdrant collection {collection_name!r} expects {configured_size} dimensions, "
            f"but {settings.EMBEDDING_MODEL_NAME!r} produces {VECTOR_SIZE}. "
            "Use a new versioned collection name and reindex memory."
        )


def _get_encoder():
    global encoder, VECTOR_SIZE, _encoder_error, _encoder_load_attempted
    global _encoder_failure_count, _encoder_next_retry_at
    global _pending_encoder
    if encoder is not None:
        return encoder
    with _encoder_lock:
        if encoder is not None:
            return encoder
        now = time.monotonic()
        if _encoder_load_attempted and now < _encoder_next_retry_at:
            raise EmbeddingUnavailableError(_encoder_error or "Embedding initialization failed")
        _encoder_load_attempted = True
        try:
            loaded_encoder = _pending_encoder
            if loaded_encoder is None:
                loaded_encoder = SentenceTransformer(
                    settings.EMBEDDING_MODEL_NAME,
                    local_files_only=True,
                    **({"revision": settings.EMBEDDING_MODEL_REVISION}
                       if settings.EMBEDDING_MODEL_REVISION else {}),
                )
            VECTOR_SIZE = int(loaded_encoder.get_sentence_embedding_dimension())
            # Store readiness can fail independently of model loading. Retain
            # valid weights across backoff instead of reloading them each time.
            _pending_encoder = loaded_encoder
            _ensure_collection(COLLECTION_NAME)
            encoder = loaded_encoder
            _pending_encoder = None
            _encoder_error = None
            _encoder_failure_count = 0
            _encoder_next_retry_at = 0.0
            return encoder
        except Exception as exc:  # pragma: no cover - depends on local model files
            _encoder_error = str(exc)
            encoder = None
            VECTOR_SIZE = 0
            _encoder_failure_count += 1
            base_delay = max(float(settings.EMBEDDING_INIT_RETRY_BASE_SECONDS), 0.0)
            max_delay = max(float(settings.EMBEDDING_INIT_RETRY_MAX_SECONDS), base_delay)
            retry_delay = min(base_delay * (2 ** min(_encoder_failure_count - 1, 8)), max_delay)
            _encoder_next_retry_at = time.monotonic() + retry_delay
            logger.exception("Failed to initialize embedding model %s", settings.EMBEDDING_MODEL_NAME)
            raise EmbeddingUnavailableError(_encoder_error) from exc


def reset_embedding_initialization() -> None:
    """Clear a failed initialization latch for an operator-triggered warmup."""
    global encoder, VECTOR_SIZE, _encoder_error, _encoder_load_attempted
    global _encoder_failure_count, _encoder_next_retry_at
    global _pending_encoder
    with _encoder_lock:
        if encoder is not None:
            return
        encoder = None
        VECTOR_SIZE = 0
        _encoder_error = None
        _encoder_load_attempted = False
        _encoder_failure_count = 0
        _encoder_next_retry_at = 0.0
        _pending_encoder = None


def _embedding_input(text: str, purpose: Literal["query", "passage"]) -> str:
    clean_text = " ".join(str(text or "").split())
    if not clean_text:
        raise ValueError("Cannot embed empty text")
    if "e5" in settings.EMBEDDING_MODEL_NAME.lower():
        return f"{purpose}: {clean_text}"
    return clean_text


def embed_text(text: str, *, purpose: Literal["query", "passage"] = "query") -> list[float]:
    """Return a normalized semantic vector or fail explicitly."""
    active_encoder = _get_encoder()

    raw_vector = active_encoder.encode(
        _embedding_input(text, purpose),
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    vector = [float(value) for value in raw_vector.tolist()]
    magnitude = math.sqrt(sum(value * value for value in vector))
    if len(vector) != VECTOR_SIZE or not math.isfinite(magnitude) or magnitude <= 1e-9:
        raise EmbeddingUnavailableError("Embedding model returned an invalid vector")
    return vector


def embed_texts(texts: list[str], *, purpose: Literal["query", "passage"] = "passage") -> list[list[float]]:
    """Embed a bounded chunk batch in one model call."""
    if not texts:
        return []
    active_encoder = _get_encoder()
    raw_vectors = active_encoder.encode(
        [_embedding_input(text, purpose) for text in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=min(len(texts), 16),
    )
    vectors: list[list[float]] = []
    for raw_vector in raw_vectors:
        vector = [float(value) for value in raw_vector.tolist()]
        magnitude = math.sqrt(sum(value * value for value in vector))
        if len(vector) != VECTOR_SIZE or not math.isfinite(magnitude) or magnitude <= 1e-9:
            raise EmbeddingUnavailableError("Embedding model returned an invalid vector")
        vectors.append(vector)
    return vectors


def _fallback_chunk_offsets(text: str, tokenizer, model_limit: int) -> list[tuple[int, int]]:
    """Support slow tokenizers using exact token counts, never a character guess."""
    def count(start: int, end: int) -> int:
        return len(tokenizer(
            _embedding_input(text[start:end], "passage"),
            add_special_tokens=True, truncation=False,
        )["input_ids"])

    offsets: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        while start < length and text[start].isspace():
            start += 1
        if start >= length:
            break
        low, high = start + 1, min(start + model_limit * 8, length)
        if count(start, low) > model_limit:
            raise EmbeddingUnavailableError("One memory character exceeds the embedding token budget")
        while low < high:
            middle = (low + high + 1) // 2
            if count(start, middle) <= model_limit:
                low = middle
            else:
                high = middle - 1
        end = low
        offsets.append((start, end))
        if end >= length:
            break
        start = max(end - min(64, (end - start) // 4), start + 1)
    return offsets


def _memory_chunk_offsets(text: str, *, max_tokens: int = 440, overlap_tokens: int = 64) -> list[tuple[int, int]]:
    """Initialize first, then chunk against the configured model's real window."""
    active_encoder = _get_encoder()
    tokenizer = getattr(active_encoder, "tokenizer", None)
    if tokenizer is None:
        raise EmbeddingUnavailableError("Embedding model has no tokenizer for bounded memory chunking")
    model_limit = getattr(active_encoder, "max_seq_length", 512)
    if not isinstance(model_limit, int):
        model_limit = 512
    if model_limit <= 16:
        raise EmbeddingUnavailableError("Embedding model token window is too small for passage input")
    max_tokens = min(max(int(max_tokens), 1), model_limit - 16)
    overlap_tokens = min(max(int(overlap_tokens), 0), max_tokens // 4)
    try:
        encoded = tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        token_offsets = [
            (int(start), int(end))
            for start, end in encoded.get("offset_mapping", [])
            if int(end) > int(start)
        ]
    except Exception:
        logger.info("Tokenizer offsets unavailable; using exact token-count chunking")
        return _fallback_chunk_offsets(text, tokenizer, model_limit)
    if not token_offsets:
        return _fallback_chunk_offsets(text, tokenizer, model_limit)
    chunks: list[tuple[int, int]] = []
    token_start = 0
    while token_start < len(token_offsets):
        token_end = min(token_start + max_tokens, len(token_offsets))
        chunks.append((token_offsets[token_start][0], token_offsets[token_end - 1][1]))
        if token_end >= len(token_offsets):
            break
        token_start = max(token_end - overlap_tokens, token_start + 1)
    chunks[0] = (0, chunks[0][1])
    chunks[-1] = (chunks[-1][0], len(text))
    # Tokenization at a new chunk boundary can differ from the full-document
    # tokenization. Check the actual passage prefix and special tokens too.
    if any(
        len(tokenizer(
            _embedding_input(text[start:end], "passage"),
            add_special_tokens=True, truncation=False,
        )["input_ids"]) > model_limit
        for start, end in chunks
    ):
        return _fallback_chunk_offsets(text, tokenizer, model_limit)
    return chunks


def _chunk_point_id(event_id: str, chunk_index: int) -> str:
    if chunk_index == 0:
        return event_id
    try:
        namespace = uuid.UUID(event_id)
    except (ValueError, TypeError, AttributeError):
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, event_id)
    return str(uuid.uuid5(namespace, f"chunk:{chunk_index}"))


def embedding_signature() -> str:
    """Identify the embedding space and preprocessing, including same-size models."""
    identity = f"{settings.EMBEDDING_MODEL_NAME}|{settings.EMBEDDING_MODEL_REVISION}|normalized:e5-prefix:v1|token-chunks:v2"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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
        "embedding_signature": embedding_signature(),
        "interaction_fingerprint": hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
    })
    if dedup_key:
        metadata["legacy_dedup_key"] = dedup_key

    chunk_offsets = _memory_chunk_offsets(clean_text)
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
    expected_ids = [_chunk_point_id(event_id, index) for index in range(len(chunk_payloads))]
    qdrant = _get_client()
    if only_if_changed:
        existing = {}
        # Keep point reads bounded even for a very large assertion document.
        for start in range(0, len(expected_ids), 64):
            existing.update({str(point.id): point for point in qdrant.retrieve(
                collection_name=COLLECTION_NAME, ids=expected_ids[start:start + 64],
                with_payload=True, with_vectors=False,
            )})
        current = all(
            str(point_id) in existing
            and all((existing[str(point_id)].payload or {}).get(key) == value
                    for key, value in payload.items())
            for point_id, (_, payload) in zip(expected_ids, chunk_payloads)
        )
        if current:
            qdrant.delete(collection_name=COLLECTION_NAME, points_selector=Filter(
                must=[FieldCondition(key="event_id", match=MatchValue(value=event_id))],
                must_not=[HasIdCondition(has_id=expected_ids)],
            ))
            return event_id, False
    if len(chunk_payloads) == 1:
        vectors = [embed_text(chunk_payloads[0][0], purpose="passage")]
    else:
        vectors = embed_texts([item[0] for item in chunk_payloads], purpose="passage")
    if len(vectors) != len(chunk_payloads):
        raise EmbeddingUnavailableError("Embedding model returned an incomplete chunk batch")
    points = [
        PointStruct(
            id=_chunk_point_id(event_id, chunk_index),
            vector=vector,
            payload=payload,
        )
        for chunk_index, ((_, payload), vector) in enumerate(zip(chunk_payloads, vectors))
    ]
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
    )
    if only_if_changed:
        # Remove obsolete chunks of this event after the new projection is
        # durable. Other events are not deleted by a count-based assumption.
        qdrant.delete(collection_name=COLLECTION_NAME, points_selector=Filter(
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
    search_result = _get_client().query_points(
        collection_name=COLLECTION_NAME,
        query=embed_text(query, purpose="query"),
        query_filter=Filter(
            must=[
                FieldCondition(key="source_role", match=MatchValue(value="user")),
                FieldCondition(key="epistemic_status", match=MatchValue(value="user_assertion")),
                FieldCondition(key="evidence_version", match=MatchValue(value=2)),
                FieldCondition(key="embedding_signature", match=MatchValue(value=embedding_signature())),
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
    search_result = _get_client().query_points(
        collection_name=COLLECTION_NAME,
        query=embed_text(query, purpose="query"),
        query_filter=Filter(
            must=[
                FieldCondition(key="source_role", match=MatchValue(value="user")),
                FieldCondition(key="epistemic_status", match=MatchValue(value="user_assertion")),
                FieldCondition(key="evidence_version", match=MatchValue(value=2)),
                FieldCondition(key="scope", match=MatchValue(value="project")),
                FieldCondition(key="embedding_signature", match=MatchValue(value=embedding_signature())),
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
    qdrant = _get_client()
    for message_id in clean_ids:
        qdrant.set_payload(
            collection_name=COLLECTION_NAME,
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
    collection_names = tuple(dict.fromkeys((COLLECTION_NAME, LEGACY_COLLECTION_NAME)))
    qdrant = _get_client()
    for collection_name in collection_names:
        try:
            qdrant.get_collection(collection_name=collection_name)
            qdrant.delete(collection_name=collection_name, points_selector=selector)
        except Exception as exc:
            errors.append(exc)
            logger.warning("Could not delete session vectors from %s: %s", collection_name, exc)
    if len(errors) == len(collection_names):
        raise RuntimeError(f"Qdrant session deletion failed: {errors[-1]}")


def get_stats() -> dict:
    try:
        count_result = _get_client().count(collection_name=COLLECTION_NAME)
        return {
            "vectors": count_result.count,
            "available": encoder is not None,
            "collection": COLLECTION_NAME,
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
            "dimensions": VECTOR_SIZE,
            "score_threshold": settings.MEMORY_SEARCH_SCORE_THRESHOLD,
        }
    except Exception as exc:
        logger.error("Error counting Qdrant vectors: %s", exc)
        return {
            "vectors": 0,
            "available": False,
            "collection": COLLECTION_NAME,
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
            "dimensions": VECTOR_SIZE,
            "score_threshold": settings.MEMORY_SEARCH_SCORE_THRESHOLD,
            "error": str(exc),
        }


def warmup_embedding_model(*, force_retry: bool = False) -> dict:
    """Load and validate the local encoder without blocking API startup."""
    if force_retry:
        reset_embedding_initialization()
    _get_encoder()
    # A normalized probe catches tokenizer/model corruption before user recall.
    probe = embed_text("uji kesehatan memori claire", purpose="query")
    return {
        "ready": True,
        "model": settings.EMBEDDING_MODEL_NAME,
        "dimensions": len(probe),
        "collection": COLLECTION_NAME,
    }
