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



class WebToolPolicy:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    def tool_arguments(self, call: Any) -> dict[str, Any]:
        raw_arguments = str(call.function.arguments or "{}")
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return parsed

    def web_search_plan_from_call(self, call: Any):
        WebSearchPlan = self.web.WebSearchPlan
    
        arguments = self.tool_arguments(call)
        raw_queries = arguments.get("queries")
        if not isinstance(raw_queries, list):
            raise ValueError("web_search requires a queries array")
        queries: list[str] = []
        for raw_query in raw_queries[:3]:
            query = " ".join(str(raw_query or "").split())[:300]
            if query and query not in queries:
                queries.append(query)
        if not queries:
            raise ValueError("web_search received no usable query")
        raw_time_range = arguments.get("time_range")
        time_range = raw_time_range if raw_time_range in {"day", "month", "year"} else None
        research_goal = " ".join(str(arguments.get("research_goal") or "").split())[:500]
        return WebSearchPlan(
            True,
            query=queries[0],
            queries=tuple(queries),
            time_range=time_range,
            reason="llm_tool_call",
            research_goal=research_goal or queries[0],
        )

    def web_tools_allowed_for_turn(self, 
        user_message: str,
        memory_context: MemoryContext,
    ) -> bool:
        """Keep internal project recall on memory stores unless web was explicitly requested."""
        plan_web_search = self.web.plan_web_search
    
        scope = memory_context.project_scope
        if scope.status == "ambiguous":
            return False
        if scope.status != "resolved" or not scope.project_id:
            return True
        explicitly_requests_web = plan_web_search(user_message).needed or bool(
            re.search(
                r"\b(?:internet|web\s+search|search\s+(?:web|internet)|browsing)\b",
                user_message,
                flags=re.IGNORECASE,
            )
        )
        if explicitly_requests_web:
            return True
    
        public_information_intent = bool(re.search(
            r"\b(?:apa\s+(?:itu|beda)|perbedaan|bandingkan|compare|comparison|versus|vs|"
            r"rekomendasi|referensi|dokumentasi|documentation)\b|"
            r"\b(?:harga|tarif|kurs|cuaca|berita|rilis|regulasi|kebijakan|versi)\b"
            r".*\b(?:hari\s+ini|terbaru|terkini|saat\s+ini|sekarang|latest|today|current)\b",
            user_message, flags=re.IGNORECASE,
        ))
        if public_information_intent:
            return True
    
        # A scope inferred from the current message/history is an internal-project
        # turn. In a project session, however, unrelated public questions must keep
        # web access even when vector/graph retrieval happened to return a hit.
        if scope.resolution != "session":
            return False
        normalized_project_name = " ".join(str(scope.project_name or "").casefold().split())
        names_active_project = bool(
            normalized_project_name
            and re.search(
                rf"(?<!\w){re.escape(normalized_project_name)}(?!\w)",
                " ".join(user_message.casefold().split()),
            )
        )
        owned_project_reference = bool(
            re.search(
                r"\b(?:project|proyek|projek)(?:\s*-?\s*(?:ku|saya|aku|gw|gue|milikku|ini|itu|tersebut))\b",
                user_message,
                flags=re.IGNORECASE,
            )
        )
        if names_active_project or owned_project_reference:
            return False
        return True
