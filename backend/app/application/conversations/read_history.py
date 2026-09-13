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

class ReadHistory:
    def get_session_history(self, db: Any, session_id: str, limit: int = 30):
        """
    Mengambil N pesan terakhir dari sebuah sesi (Short-Term Memory).
    """
        db = self.persistence.wrap(db)
        if not session_id:
            return []
            
        messages = (
            db.get_session_history_messages(limit, session_id)
        )
        
        history = []
        for msg in reversed(messages):
            history.append({"role": msg.role, "content": msg.content})
            
        return history

    def get_session_summary(self, db: Any, session_id: str) -> str:
        db = self.persistence.wrap(db)
        if not session_id:
            return ""
        row = db.get_session_summary_row(session_id)
        return str(row[0] or "") if row else ""
