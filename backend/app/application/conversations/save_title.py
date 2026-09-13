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

class SaveTitle:
    def generate_and_save_title(self, session_id: str, first_message: str):
        """
    Fungsi background task untuk men-generate judul sesi dan menyimpannya ke SQLite.
    """
        try:
            db = self.persistence.open()
            try:
                with self.usage_context(conversation_id=session_id, turn_id=None, job_id=None, job_attempt=None):
                    title = self.generate_session_title(first_message)
                
                conv = db.generate_and_save_title_conv(session_id)
                if conv:
                    conv.title = title
                    db.commit()
                    logger.info(f" -> Session title updated to: '{title}'")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in background task generate_and_save_title: {e}")
