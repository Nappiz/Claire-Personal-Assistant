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

class ProviderSerializers:
    def serialized_tool_calls(self, tool_calls: list[Any]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for call in tool_calls:
            if hasattr(call, "model_dump"):
                payload = call.model_dump(exclude_none=True)
            elif isinstance(call, dict):
                payload = dict(call)
            else:
                payload = {}
    
            # Gemini 3 puts its required encrypted thought signature in this
            # provider extension. Never synthesize or modify it: replay exactly
            # what the provider returned for the corresponding function call.
            extra_content = getattr(call, "extra_content", None) or payload.get("extra_content")
            if extra_content is not None and "extra_content" not in payload:
                payload["extra_content"] = (
                    extra_content.model_dump(exclude_none=True)
                    if hasattr(extra_content, "model_dump")
                    else extra_content
                )
    
            function = getattr(call, "function", None)
            function_payload = payload.get("function") or {}
            call_id = getattr(call, "id", None) or payload.get("id")
            function_name = getattr(function, "name", None) or function_payload.get("name")
            function_arguments = (
                getattr(function, "arguments", None)
                or function_payload.get("arguments")
                or "{}"
            )
            payload.update(
                {
                    "id": str(call_id),
                    "type": "function",
                    "function": {
                        "name": str(function_name),
                        "arguments": str(function_arguments),
                    },
                }
            )
            serialized.append(payload)
        return serialized

    def serialized_assistant_tool_message(self, message: Any, tool_calls: list[Any]) -> dict[str, Any]:
        """Replay the provider response without dropping provider-specific metadata."""
        if hasattr(message, "model_dump"):
            payload = message.model_dump(exclude_none=True)
        elif isinstance(message, dict):
            payload = dict(message)
        else:
            payload = {}
        payload["role"] = "assistant"
        payload["content"] = str(getattr(message, "content", "") or payload.get("content") or "")
        payload["tool_calls"] = self.serialized_tool_calls(tool_calls)
        return payload
