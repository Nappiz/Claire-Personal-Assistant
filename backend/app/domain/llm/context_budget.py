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



class ContextBudget:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    def estimate_prompt_tokens(self, value: object) -> int:
        """Conservative provider-neutral estimate using encoded byte volume."""
        text = str(value or "")
        return max(1, (len(text.encode("utf-8")) + 1) // 2)

    def bounded_memory_items(self, memory_context: MemoryContext) -> tuple[list[dict], list[str]]:
        vector_items: list[dict] = []
        for raw in list(memory_context.qdrant_context or [])[:3]:
            item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
            item["content"] = str(item.get("content") or "")[:1_000]
            vector_items.append(item)
        graph_items = [str(item)[:500] for item in list(memory_context.neo4j_context or [])[:8]]
        return vector_items, graph_items

    def fit_history_to_prompt_budget(self, 
        system_prompt: str,
        user_message: str,
        session_history: list | None,
    ) -> list[dict]:
        budget = max(int(self.config.CHAT_INPUT_TOKEN_BUDGET), 4_000)
        used = self.estimate_prompt_tokens(system_prompt) + self.estimate_prompt_tokens(user_message) + 64
        selected: list[dict] = []
        for raw in reversed(list(session_history or [])):
            if not isinstance(raw, dict) or raw.get("role") not in {"user", "assistant"}:
                continue
            message = {"role": raw["role"], "content": str(raw.get("content") or "")[:12_000]}
            cost = self.estimate_prompt_tokens(message["content"]) + 8
            if used + cost > budget:
                continue
            selected.append(message)
            used += cost
        selected.reverse()
        return selected
