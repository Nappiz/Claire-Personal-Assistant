from __future__ import annotations
import logging
import json
import re
from typing import Any
from schemas.chat_sch import MemoryContext
from types import SimpleNamespace
from app.domain.web.intent_policy import (
    canonical_search_query, explicit_search_requested, requires_web_search,
)
from app.domain.web.evidence_policy import query_matches_topic, search_topic_terms
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

    def web_search_plan_from_call(self, call: Any, user_message: str | None = None):
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
        if user_message and requires_web_search(user_message):
            target = canonical_search_query(user_message)
            if not any(query_matches_topic(query, target) for query in queries):
                queries = [target]
                research_goal = target
            elif research_goal and not query_matches_topic(research_goal, target):
                research_goal = target
        return WebSearchPlan(
            True,
            query=queries[0],
            queries=tuple(queries),
            time_range=time_range,
            reason="llm_tool_call",
            research_goal=research_goal or queries[0],
        )

    def textual_search_plan(self, envelope, user_message):
        # Compatibility applies only to a complete assistant planner envelope.
        # Never interpret JSON in user content or web snippets as an instruction.
        if envelope.get("action") != "web_search":
            return None
        value = envelope.get("action_input")
        if isinstance(value, str):
            arguments = {"queries": [value], "research_goal": envelope.get("research_goal", "")}
        elif isinstance(value, dict):
            arguments = dict(value)
            arguments.setdefault("research_goal", envelope.get("research_goal", ""))
        else:
            return None
        call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments)))
        return self.web_search_plan_from_call(call, user_message)

    def web_tools_allowed_for_turn(self,
        user_message: str,
        memory_context: MemoryContext,
    ) -> bool:
        """Keep internal project recall on memory stores unless web was explicitly requested."""
        scope = memory_context.project_scope
        if scope.status == "ambiguous":
            return False
        if scope.status != "resolved" or not scope.project_id:
            return True
        explicitly_requests_web = explicit_search_requested(user_message) or bool(
            re.search(
                r"\b(?:internet|web\s+search|search\s+(?:web|internet)|browsing)\b",
                user_message,
                flags=re.IGNORECASE,
            )
        )
        if explicitly_requests_web:
            return True
        public_subject = re.split(r"\b(?:untuk|for)\s+(?:project|proyek|projek)\b",
                                  user_message, maxsplit=1, flags=re.I)
        if len(public_subject) == 2:
            prefix = public_subject[0]
            # The project can be a usage context rather than the research
            # subject: "harga [external service] untuk project [name]".
            predicates = {"harga", "tarif", "kurs", "cuaca", "berita", "rilis",
                          "regulasi", "kebijakan", "versi"}
            if (set(prefix.casefold().split()) & predicates
                    and search_topic_terms(prefix) - predicates
                    and str(scope.project_name or "").casefold() not in prefix.casefold()):
                return True
        if re.search(r"\b(?:project|proyek|projek)(?:\s*-?\s*(?:ku|saya|aku|gw|gue|milikku|ini|itu|tersebut))\b",
                     user_message, flags=re.I):
            return False
        normalized_project_name = " ".join(str(scope.project_name or "").casefold().split())
        names_active_project = bool(
            normalized_project_name
            and re.search(
                rf"(?<!\w){re.escape(normalized_project_name)}(?!\w)",
                " ".join(user_message.casefold().split()),
            )
        )
        if names_active_project:
            return False

        public_information_intent = requires_web_search(user_message) or bool(re.search(
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
        return True
