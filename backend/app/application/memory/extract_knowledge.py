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

class ExtractKnowledge:
    def extract_knowledge(self, 
        user_message: str,
        neo4j_context: list = None,
        session_history: list | None = None,
        raise_on_error: bool = False,
        project_id: str | None = None,
        project_name: str | None = None,
        event_at: datetime | None = None,
    ) -> dict:
        """
    Tugas khusus untuk Slow Lane: 
    Menganalisis pesan pengguna dan mengekstrak fakta penting menjadi format JSON (Nodes & Edges).
    """
        if self.extraction.is_memory_recall_question(user_message):
            logger.info("Skipping knowledge extraction for recall-only question: %s", user_message)
            return {"nodes": [], "edges": []}
    
        system_prompt = self.prompts.build_extraction_prompt(user_message, neo4j_context, session_history, project_id, project_name, event_at)
        
        content = ""
        try:
            response = self.gateway.memory_completion(
                purpose="extraction",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content.strip()
            
            # Accept an enclosing code fence, but never carve an arbitrary object
            # out of an array/error wrapper and silently reinterpret its schema.
            fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", content, flags=re.IGNORECASE)
            if fenced:
                content = fenced.group(1).strip()
                
            raw_extraction = self.extraction.validate_extraction_envelope(json.loads(content))
            sanitized = self.extraction.sanitize_extracted_knowledge(raw_extraction)
            sanitized = self.ground_locations(sanitized, user_message, session_history, neo4j_context)
            if project_id and (sanitized.get("edges") or sanitized.get("retractions")):
                existing_ids = {str(node.get("id")) for node in sanitized.get("nodes", [])}
                normalized_project_id = " ".join(str(project_id).casefold().split())
                normalized_project_name = " ".join(str(project_name or project_id).casefold().split())
                existing_project = next(
                    (
                        node
                        for node in sanitized.get("nodes", [])
                        if str(node.get("label", "")).lower() == "project"
                        and (
                            " ".join(str(node.get("identity_context", "")).casefold().split())
                            == normalized_project_id
                            or " ".join(str(node.get("name", "")).casefold().split())
                            in {normalized_project_id, normalized_project_name}
                        )
                    ),
                    None,
                )
                if existing_project:
                    project_ref = str(existing_project["id"])
                    existing_project["name"] = str(project_name or project_id).strip().lower()
                    existing_project["identity_context"] = str(project_id)
                    existing_project["confidence"] = 1.0
                else:
                    project_ref = "active_project"
                    while project_ref in existing_ids:
                        project_ref += "_scope"
                    sanitized["nodes"].append(
                        {
                            "id": project_ref,
                            "label": "Project",
                            "name": str(project_name or project_id).strip().lower(),
                            "identity_context": str(project_id),
                            "confidence": 1.0,
                        }
                    )
                connected_ids = {
                    str(value)
                    for edge in sanitized["edges"]
                    for value in (edge.get("source"), edge.get("target"))
                    if value
                }
                nodes_by_id = {str(node.get("id")): node for node in sanitized["nodes"]}
                for node_id in sorted(connected_ids):
                    node = nodes_by_id.get(node_id)
                    if not node or str(node.get("label", "")).lower() in {"person", "project"}:
                        continue
                    sanitized["edges"].append(
                        {
                            "source": node_id,
                            "target": project_ref,
                            "relation": "BELONGS_TO",
                            "supersedes": [],
                            "replaces_current_relation": False,
                            "confidence": 1.0,
                        }
                    )
            return validate_extracted_knowledge(sanitized)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM in extract_knowledge: {e}. Raw content: {content}")
            if raise_on_error:
                raise
            return {"nodes": [], "edges": []}
        except Exception as e:
            logger.error(f"Error calling LLM API in extract_knowledge: {e}")
            if raise_on_error:
                raise
            return {"nodes": [], "edges": []}
