from __future__ import annotations
import asyncio
import logging
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from schemas.chat_sch import MemoryContext, WebPageContent, WebSearchContext
from app.domain.llm.contracts import DEFAULT_MODEL_NAME, ERROR_FALLBACK_MSG, MemoryLLMUnavailableError, MemoryRouteDecision
from app.domain.graph.fact_policy import get_relation_policy, validate_extracted_knowledge, RELATION_POLICIES
from app.domain.diagnostics import InternalFeatureError
from app.domain.llm.contracts import CONTEXT_REFERENCE_RE, GENERIC_ENTITY_REFERENCES, QUESTION_CLAUSE_RE
from app.domain.llm.tool_contracts import WEB_TOOL_DEFINITIONS, WEB_TOOL_INSTRUCTIONS
logger = logging.getLogger("services.llm_service")

class GenerateTitle:
    def generate_session_title(self, user_message: str) -> str:
        """
    Men-generate judul percakapan pendek (3-5 kata) berdasarkan pesan pertama user.
    """
        logger.info(f"Generating session title for: {user_message}")
        
        prompt = f"""
Tugasmu adalah membuat judul singkat untuk sebuah percakapan chat.
Judul HARUS maksimal 5 kata. Jangan gunakan tanda kutip, titik, atau format tambahan.
Hanya kembalikan teks judulnya saja secara langsung.

Pesan Pertama: {user_message}
Judul:
"""
        try:
            response = self.gateway.memory_completion(
                purpose="title",
                messages=[{"role": "user", "content": prompt.strip()}],
                temperature=0.3,
                max_tokens=20,
            )
            title = response.choices[0].message.content.strip()
            title = title.replace('"', '').replace("'", "")
            return title
        except Exception as e:
            logger.error(f"Error generating session title: {e}")
            return "Percakapan Baru"
