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



class ResponsePolicy:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    def usage_values(self, value: Any) -> dict[str, int]:
        if value is None:
            return {}
        usage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            count = value.get(key) if isinstance(value, dict) else getattr(value, key, None)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                usage[key] = count
        if "total_tokens" not in usage and all(key in usage for key in ("prompt_tokens", "completion_tokens")):
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return usage

    def add_usage(self, total: dict, value: Any, invocation_id: str | None = None) -> None:
        usage = self.usage_values(value)
        for key, value in usage.items():
            total[key] = total.get(key, 0) + value
        if invocation_id and invocation_id not in total.setdefault("invocation_ids", []):
            total["invocation_ids"].append(invocation_id)

    def finish_reason_text(self, value: Any) -> str:
        """Normalize SDK/provider finish-reason objects for safe diagnostics."""
        if value is None:
            return ""
        enum_value = getattr(value, "value", None)
        return str(enum_value if enum_value is not None else value)

    def stream_delta_text(self, delta: Any) -> str:
        """Extract visible text while tolerating OpenAI-compatible content parts."""
        content = getattr(delta, "content", None)
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
    
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
            else:
                text = getattr(part, "text", None)
            if isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts)

    def record_stream_diagnostics(self, choice: Any, diagnostics: dict[str, Any]) -> None:
        finish_reason = self.finish_reason_text(getattr(choice, "finish_reason", None))
        if finish_reason and finish_reason not in diagnostics["finish_reasons"]:
            diagnostics["finish_reasons"].append(finish_reason)
    
        delta = getattr(choice, "delta", None)
        if delta is None:
            return
    
        refusal = getattr(delta, "refusal", None)
        if refusal:
            diagnostics["refusal"] = str(refusal)[:500]
    
        for tool_call in getattr(delta, "tool_calls", None) or []:
            function = getattr(tool_call, "function", None)
            name = getattr(function, "name", None)
            normalized_name = str(name or "unknown_tool")
            if normalized_name not in diagnostics["tool_calls"]:
                diagnostics["tool_calls"].append(normalized_name)

    def completion_outcome(self, diagnostics: dict) -> dict:
        reasons = diagnostics.get("finish_reasons", [])
        reason = reasons[-1] if reasons else None
        incomplete = str(reason or "").lower() in {"length", "max_tokens", "max_output_tokens", "content_filter"}
        return {"type": "completion", "response_status": "incomplete" if incomplete else "complete",
                "finish_reason": reason}
