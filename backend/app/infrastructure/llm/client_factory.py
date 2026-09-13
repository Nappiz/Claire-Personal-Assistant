from __future__ import annotations
import logging
from typing import Any
logger = logging.getLogger("services.llm_service")
from openai import AsyncOpenAI, OpenAI
from configs.settings import settings
from configs.database import SessionLocal
from app.infrastructure.persistence.settings import SQLAlchemySettingsRepository

def get_setting(db, key, default_value=None):
    return SQLAlchemySettingsRepository(db).get(key, default_value)

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
