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

class RouteMemoryQuery:
    def route_memory_query(self, user_message: str, session_history: list | None = None,
                           session_summary: str | None = None) -> MemoryRouteDecision:
        """Classify personal-memory intent without conflating failure with no intent."""
        system_prompt, discourse = self.prompts.build_memory_query_prompt(user_message, session_history, session_summary)
        content = ""
        try:
            response = self.gateway.memory_completion(
                purpose="router",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1,
                client_timeout=max(
                    min(
                        float(self.config.MEMORY_RETRIEVAL_TIMEOUT_SECONDS) - 0.25,
                        float(self.config.MEMORY_LLM_TIMEOUT_SECONDS),
                    ),
                    0.5,
                ),
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content.strip()
            
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
    
            data = json.loads(content)
            if not isinstance(data, dict) or not isinstance(data.get("keywords", []), list):
                raise ValueError("Memory router returned an invalid schema")
            keywords: list[str] = []
            for keyword in data.get("keywords", [])[:5]:
                clean_keyword = " ".join(str(keyword).lower().split())[:100]
                if clean_keyword and clean_keyword not in keywords:
                    keywords.append(clean_keyword)
            needs_memory = bool(data.get("needs_memory", keywords))
            query = user_message
            reference_status = "none"
            confidence = 0.0
            candidates = []
            context_text = " ".join([discourse["current_message"], discourse["summary"], *[item["content"] for item in discourse["history"]]]).casefold()
            local_person = self.references.inline_person_reference(user_message)
            if local_person:
                data = {**data, "reference_status": "resolved", "confidence": 1.0,
                        "references": [{"mention": "dia", "entity": local_person}], "candidates": [local_person]}
            if self.references.reference_matches(user_message) and (
                needs_memory or data.get("reference_status") in {"resolved", "ambiguous"}
            ):
                reference_status = "ambiguous"
                confidence = float(data.get("confidence", 0.0))
                if not 0.0 <= confidence <= 1.0:
                    raise ValueError("Invalid reference confidence")
                for candidate in data.get("candidates", [])[:5]:
                    candidate = " ".join(str(candidate).split())[:100]
                    if candidate and re.search(rf"(?<!\w){re.escape(candidate.casefold())}(?!\w)", context_text):
                        candidates.append(candidate)
                references = data.get("references", [])
                if (data.get("reference_status") == "resolved" and confidence >= 0.85
                        and isinstance(references, list) and references):
                    replacements = {}
                    for reference in references[:5]:
                        if not isinstance(reference, dict):
                            raise ValueError("Invalid reference mapping")
                        mention = str(reference.get("mention") or "").casefold()
                        entity = " ".join(str(reference.get("entity") or "").split())[:100]
                        if not CONTEXT_REFERENCE_RE.fullmatch(mention) and mention != "nya":
                            raise ValueError("Reference mention is not a supported pronoun")
                        if not entity or not re.search(rf"(?<!\w){re.escape(entity.casefold())}(?!\w)", context_text):
                            raise ValueError("Reference entity is absent from supplied context")
                        if mention in replacements and replacements[mention] != entity:
                            raise ValueError("Conflicting reference mappings")
                        replacements[mention] = entity
                    mentions = {match.group().casefold() for match in self.references.reference_matches(user_message)}
                    reference_spans = {match.span() for match in self.references.reference_matches(user_message)}
                    if mentions.issubset(replacements):
                        query = CONTEXT_REFERENCE_RE.sub(
                            lambda match: ((" " if match.group().casefold() == "nya" else "")
                                           + replacements[match.group().casefold()])
                            if match.group().casefold() in replacements and match.span() in reference_spans
                            else match.group(), user_message
                        )
                    if query != user_message and not self.references.reference_matches(query):
                        reference_status = "resolved"
                        keywords = list(dict.fromkeys([*replacements.values(), *[
                            keyword for keyword in keywords
                            if keyword.casefold() in query.casefold()
                            or keyword.upper().replace(" ", "_") in RELATION_POLICIES
                        ]]))
                        candidates = list(dict.fromkeys(replacements.values()))
            return MemoryRouteDecision("needed" if needs_memory else "not_needed", keywords,
                                       query=query, reference_status=reference_status,
                                       candidates=tuple(candidates), confidence=confidence)
        except Exception as exc:
            logger.error("Memory router failed: %s; raw=%r", exc, content[:500])
            return MemoryRouteDecision("router_failed", [], str(exc), query=user_message,
                reference_status="ambiguous" if self.references.reference_matches(user_message) else "none")

    def generate_search_queries(self, user_message: str) -> list[str]:
        """Compatibility wrapper for callers that only need the keyword list."""
        return self.route_memory_query(user_message).keywords
