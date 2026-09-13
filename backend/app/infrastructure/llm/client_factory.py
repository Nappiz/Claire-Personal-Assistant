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
from openai import AsyncOpenAI, OpenAI
from configs.settings import settings
from configs.database import SessionLocal
from services.settings_service import get_setting

def get_llm_connection(provider: str | None = None) -> tuple[str | None, str | None]:
    """Resolve provider credentials without exposing keys outside this module."""
    db = SessionLocal()
    try:
        api_keys = get_setting(db, "api_keys", default_value={})
        provider = provider or "google"

        if provider == "google":
            key = api_keys.get("google") or settings.GEMINI_API_KEY
            return key, "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif provider == "groq":
            key = api_keys.get("groq") or settings.GROQ_API_KEY
            return key, "https://api.groq.com/openai/v1"
        elif provider == "openai":
            key = api_keys.get("openai")
            return key, None
        elif provider == "huggingface":
            key = api_keys.get("hf")
            return key, "https://router.huggingface.co/v1"
        raise ValueError(f"Unsupported LLM provider: {provider}")
    finally:
        db.close()

def get_llm_client(
    provider: str | None = None,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> OpenAI:
    """Create the synchronous client used by non-streaming background work."""
    api_key, base_url = get_llm_connection(provider)
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS,
        "max_retries": max_retries if max_retries is not None else settings.LLM_MAX_RETRIES,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)

def get_async_llm_client(provider: str | None = None) -> AsyncOpenAI:
    """Create a non-blocking client for user-facing streaming requests."""
    api_key, base_url = get_llm_connection(provider)
    return create_async_llm_client(api_key, base_url)

def create_async_llm_client(api_key: str | None, base_url: str | None) -> AsyncOpenAI:
    kwargs = {
        "api_key": api_key,
        "max_retries": settings.LLM_MAX_RETRIES,
        "timeout": settings.LLM_TIMEOUT_SECONDS,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)
