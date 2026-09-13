from __future__ import annotations
import logging
from configs.settings import settings
from . import state

logger = logging.getLogger(__name__)
from . import qdrant_client_factory
from . import embedding_encoder

def get_stats() -> dict:
    try:
        count_result = qdrant_client_factory._get_client().count(collection_name=state.COLLECTION_NAME)
        return {
            "vectors": count_result.count,
            "available": state.encoder is not None,
            "collection": state.COLLECTION_NAME,
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
            "dimensions": state.VECTOR_SIZE,
            "score_threshold": settings.MEMORY_SEARCH_SCORE_THRESHOLD,
        }
    except Exception as exc:
        logger.error("Error counting Qdrant vectors: %s", exc)
        return {
            "vectors": 0,
            "available": False,
            "collection": state.COLLECTION_NAME,
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
            "dimensions": state.VECTOR_SIZE,
            "score_threshold": settings.MEMORY_SEARCH_SCORE_THRESHOLD,
            "error": str(exc),
        }

def warmup_embedding_model(*, force_retry: bool = False) -> dict:
    """Load and validate the local encoder without blocking API startup."""
    if force_retry:
        embedding_encoder.reset_embedding_initialization()
    embedding_encoder._get_encoder()
    # A normalized probe catches tokenizer/model corruption before user recall.
    probe = embedding_encoder.embed_text("uji kesehatan memori claire", purpose="query")
    return {
        "ready": True,
        "model": settings.EMBEDDING_MODEL_NAME,
        "dimensions": len(probe),
        "collection": state.COLLECTION_NAME,
    }
