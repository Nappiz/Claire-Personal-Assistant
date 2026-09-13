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

class ScopePolicy:
    def __init__(self, config):
        self.config = config

    def normalized_text(self, value: object) -> str:
        return " ".join(str(value or "").casefold().split())

    def mentions_project_name(self, text: str, project_name: str) -> bool:
        normalized_text = self.normalized_text(text)
        normalized_name = self.normalized_text(project_name)
        if not normalized_name:
            return False
        return bool(
            re.search(
                rf"(?<!\w){re.escape(normalized_name)}(?!\w)",
                normalized_text,
                flags=re.UNICODE,
            )
        )
