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


def _get_client():
    if state.client is not None:
        return state.client
    with state._client_lock:
        if state.client is not None:
            return state.client
        try:
            state.client = QdrantClient(path=settings.QDRANT_PATH)
            state._client_error = None
            return state.client
        except Exception as exc:
            state._client_error = str(exc)
            raise RuntimeError(f"Qdrant is unavailable: {exc}") from exc

def _ensure_collection(collection_name: str) -> None:
    if state.VECTOR_SIZE <= 0:
        return
    qdrant = _get_client()
    try:
        collection = qdrant.get_collection(collection_name=collection_name)
    except Exception:
        logger.info("Creating Qdrant collection %s (%s dimensions)", collection_name, state.VECTOR_SIZE)
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=state.VECTOR_SIZE, distance=Distance.COSINE),
        )
        return

    configured_size = getattr(getattr(collection.config.params, "vectors", None), "size", None)
    if configured_size is not None and int(configured_size) != state.VECTOR_SIZE:
        raise RuntimeError(
            f"Qdrant collection {collection_name!r} expects {configured_size} dimensions, "
            f"but {settings.EMBEDDING_MODEL_NAME!r} produces {state.VECTOR_SIZE}. "
            "Use a new versioned collection name and reindex memory."
        )
