from __future__ import annotations
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Literal
from configs.settings import settings
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, IsEmptyCondition, PointStruct, HasIdCondition, VectorParams
from . import state

logger = logging.getLogger(__name__)
from . import qdrant_client_factory

if settings.HF_TOKEN:
    os.environ["HF_TOKEN"] = settings.HF_TOKEN
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from sentence_transformers import SentenceTransformer

class EmbeddingUnavailableError(RuntimeError):
    """Raised when a real semantic embedding cannot be produced safely."""

def _get_encoder():
    if state.encoder is not None:
        return state.encoder
    with state._encoder_lock:
        if state.encoder is not None:
            return state.encoder
        now = time.monotonic()
        if state._encoder_load_attempted and now < state._encoder_next_retry_at:
            raise EmbeddingUnavailableError(state._encoder_error or "Embedding initialization failed")
        state._encoder_load_attempted = True
        try:
            loaded_encoder = state._pending_encoder
            if loaded_encoder is None:
                loaded_encoder = SentenceTransformer(
                    settings.EMBEDDING_MODEL_NAME,
                    local_files_only=True,
                    **({"revision": settings.EMBEDDING_MODEL_REVISION}
                       if settings.EMBEDDING_MODEL_REVISION else {}),
                )
            state.VECTOR_SIZE = int(loaded_encoder.get_sentence_embedding_dimension())
            # Store readiness can fail independently of model loading. Retain
            # valid weights across backoff instead of reloading them each time.
            state._pending_encoder = loaded_encoder
            qdrant_client_factory._ensure_collection(state.COLLECTION_NAME)
            state.encoder = loaded_encoder
            state._pending_encoder = None
            state._encoder_error = None
            state._encoder_failure_count = 0
            state._encoder_next_retry_at = 0.0
            return state.encoder
        except Exception as exc:  # pragma: no cover - depends on local model files
            state._encoder_error = str(exc)
            state.encoder = None
            state.VECTOR_SIZE = 0
            state._encoder_failure_count += 1
            base_delay = max(float(settings.EMBEDDING_INIT_RETRY_BASE_SECONDS), 0.0)
            max_delay = max(float(settings.EMBEDDING_INIT_RETRY_MAX_SECONDS), base_delay)
            retry_delay = min(base_delay * (2 ** min(state._encoder_failure_count - 1, 8)), max_delay)
            state._encoder_next_retry_at = time.monotonic() + retry_delay
            logger.exception("Failed to initialize embedding model %s", settings.EMBEDDING_MODEL_NAME)
            raise EmbeddingUnavailableError(state._encoder_error) from exc

def reset_embedding_initialization() -> None:
    """Clear a failed initialization latch for an operator-triggered warmup."""
    with state._encoder_lock:
        if state.encoder is not None:
            return
        state.encoder = None
        state.VECTOR_SIZE = 0
        state._encoder_error = None
        state._encoder_load_attempted = False
        state._encoder_failure_count = 0
        state._encoder_next_retry_at = 0.0
        state._pending_encoder = None

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
    if len(vector) != state.VECTOR_SIZE or not math.isfinite(magnitude) or magnitude <= 1e-9:
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
        if len(vector) != state.VECTOR_SIZE or not math.isfinite(magnitude) or magnitude <= 1e-9:
            raise EmbeddingUnavailableError("Embedding model returned an invalid vector")
        vectors.append(vector)
    return vectors

def embedding_signature() -> str:
    """Identify the embedding space and preprocessing, including same-size models."""
    identity = f"{settings.EMBEDDING_MODEL_NAME}|{settings.EMBEDDING_MODEL_REVISION}|normalized:e5-prefix:v1|token-chunks:v2"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
