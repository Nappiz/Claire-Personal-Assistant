from __future__ import annotations
import logging
import traceback
import time
import uuid
import re
import concurrent.futures
from datetime import datetime, timedelta, timezone
from typing import Any
from schemas.chat_sch import MemoryContext, ProjectScopeContext, RetrievalStatus, QueryResolution
from app.domain.llm.contracts import MemoryLLMUnavailableError, ERROR_FALLBACK_MSG
from app.domain.memory.contracts import TurnConflictError, _MEMORY_RECALL_RE, _HISTORICAL_RE, _SEARCH_STOPWORDS, _VAGUE_PROJECT_REFERENCE_RE, _MEMORY_RETRY_BASE_SECONDS, _MEMORY_RETRY_MAX_SECONDS, _MEMORY_JOB_LEASE_SECONDS
from app.domain.diagnostics import InternalFeatureError, current_exception_log, redact_diagnostic_log
logger = logging.getLogger("services.memory_service")

class AssertionPolicy:
    def __init__(self, config):
        self.config = config

    def vector_assertion_evidence(self, extracted: dict | None) -> tuple[str, list[dict]]:
        """Render only validated positive assertions for semantic memory.

    SQLite retains the raw conversation. Qdrant receives compact, resolved graph
    evidence so questions, quotations, hypotheticals, and elliptical chatter are
    not mislabeled as factual assertions merely because the user authored them.
    """
        data = extracted if isinstance(extracted, dict) else {}
        nodes = {
            str(node.get("id")): node
            for node in data.get("nodes", [])
            if isinstance(node, dict) and node.get("id") and node.get("name")
        }
        spans: list[dict] = []
        rendered: list[str] = []
        seen: set[str] = set()
        evidence_offset = 0
        for edge in data.get("edges", []):
            if not isinstance(edge, dict):
                continue
            if float(edge.get("confidence", 1.0) or 0.0) < self.config.MEMORY_FACT_CONFIDENCE_THRESHOLD:
                continue
            relation = " ".join(str(edge.get("relation") or "").replace("_", " ").split()).lower()
            if not relation or relation == "belongs to":
                continue
            source = nodes.get(str(edge.get("source")))
            target = nodes.get(str(edge.get("target")))
            if not source or not target:
                continue
            if min(float(source.get("confidence", 1.0)), float(target.get("confidence", 1.0))) < self.config.MEMORY_FACT_CONFIDENCE_THRESHOLD:
                continue
            def resolved_name(node: dict) -> str:
                name = str(node["name"])
                context = str(node.get("identity_context") or "").strip()
                if str(node.get("label") or "").lower() == "person" and context:
                    return f"{name} ({context})"
                return name
            assertion = " ".join(f"{resolved_name(source)} {relation} {resolved_name(target)}".split())
            fingerprint = assertion.casefold()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            rendered.append(assertion)
            spans.append({
                "text": assertion,
                "modality": "asserted_fact",
                "polarity": "positive",
                "source_ref": str(edge.get("source")),
                "target_ref": str(edge.get("target")),
                "relation": str(edge.get("relation") or "").upper(),
                "span_start": evidence_offset,
                "span_end": evidence_offset + len(assertion),
            })
            evidence_offset += len(assertion) + 2
        return ". ".join(rendered), spans
