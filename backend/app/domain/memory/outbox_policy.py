from __future__ import annotations
import logging
import traceback
import time
import uuid
import re
import concurrent.futures
from datetime import datetime, timedelta, timezone
from typing import Any
from schemas.chat_sch import MemoryContext, ProjectScopeContext, RetrievalStatus, QueryResolution
from app.domain.llm.contracts import MemoryLLMUnavailableError, ERROR_FALLBACK_MSG
from app.domain.memory.contracts import TurnConflictError, _MEMORY_RECALL_RE, _HISTORICAL_RE, _SEARCH_STOPWORDS, _VAGUE_PROJECT_REFERENCE_RE, _MEMORY_RETRY_BASE_SECONDS, _MEMORY_RETRY_MAX_SECONDS, _MEMORY_JOB_LEASE_SECONDS
from app.domain.diagnostics import InternalFeatureError, current_exception_log, redact_diagnostic_log
logger = logging.getLogger("services.memory_service")

class OutboxPolicy:
    def __init__(self, config):
        self.config = config

    def outbox_job_data(self, job: db.new_outbox) -> dict:
        """Return only operational metadata; never expose chat payload by default."""
        return {
            "id": job.id,
            "conversation_id": job.conversation_id,
            "user_message_id": job.user_message_id,
            "status": job.status,
            "vector_saved": bool(job.vector_saved),
            "extraction_completed": bool(job.extraction_completed),
            "graph_saved": bool(job.graph_saved),
            "attempts": job.attempts,
            "last_error": job.last_error,
            "next_retry_at": job.next_retry_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
