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

class RetrieveContext:
    def retrieve_context(self, 
        user_message: str,
        *,
        raise_on_error: bool = False,
        project_id: str | None = None,
        session_history: list[dict] | None = None,
        session_summary: str | None = None,
    ) -> MemoryContext:
        """
    Mengambil konteks dari Neo4j (Long-term Facts) dan Qdrant (Semantic Search).
    Router terlebih dahulu menentukan apakah pesan memang membutuhkan memori.
    Ini penting untuk pertanyaan mandiri seperti "siapa penciptamu?": hasil
    vector search yang kebetulan mirip tidak boleh mengalihkan topik jawaban.
    """
        logger.info("Retrieving context with an end-to-end deadline")
        if self.retrieval.is_standalone_assistant_question(user_message):
            logger.info("Skipping memory retrieval for standalone question about Claire.")
            return MemoryContext(qdrant_context=[], neo4j_context=[])
        timeout_seconds = max(float(self.config.MEMORY_RETRIEVAL_TIMEOUT_SECONDS), 0.1)
        deadline = time.monotonic() + timeout_seconds
        warnings: list[str] = []
        diagnostics: list[str] = []
    
        scope_future = self.retrieval_executor.submit(
            self.resolve_project_scope,
            user_message,
            session_project_id=project_id,
            session_history=session_history,
        )
        route_future = self.retrieval_executor.submit(
            self.route_memory_query, user_message, session_history=session_history, session_summary=session_summary
        )
        concurrent.futures.wait(
            (scope_future, route_future),
            timeout=max(deadline - time.monotonic(), 0.0),
        )
    
        if scope_future.done():
            try:
                project_scope = scope_future.result()
            except Exception:
                diagnostics.append(traceback.format_exc())
                warnings.append("project_scope_unavailable")
                project_scope = ProjectScopeContext(
                    status="resolved" if project_id else ("ambiguous" if _VAGUE_PROJECT_REFERENCE_RE.search(user_message) else "none"),
                    project_id=project_id,
                    project_name=project_id,
                    resolution="session" if project_id else None,
                )
        else:
            scope_future.cancel()
            warnings.append("project_scope_timeout")
            diagnostics.append(f"Project scope resolution exceeded the {timeout_seconds}s retrieval deadline.")
            project_scope = ProjectScopeContext(
                status="resolved" if project_id else ("ambiguous" if _VAGUE_PROJECT_REFERENCE_RE.search(user_message) else "none"),
                project_id=project_id,
                project_name=project_id,
                resolution="session" if project_id else None,
            )
    
        if route_future.done():
            try:
                route = route_future.result()
            except Exception as exc:
                diagnostics.append(traceback.format_exc())
                route = type("RouteFallback", (), {"status": "router_failed", "keywords": [], "error": str(exc)})()
        else:
            route_future.cancel()
            warnings.append("memory_router_timeout")
            diagnostics.append(f"Memory router exceeded the {timeout_seconds}s retrieval deadline.")
            route = type("RouteFallback", (), {"status": "router_failed", "keywords": [], "error": "timeout"})()
    
        effective_project_id = project_scope.project_id
        query_resolution = QueryResolution(
            status=("ambiguous" if route.status == "router_failed" and self.references.reference_matches(user_message)
                    else getattr(route, "reference_status", "none")),
            query=getattr(route, "query", None) or user_message,
            candidates=list(getattr(route, "candidates", ())),
            confidence=getattr(route, "confidence", 0.0),
        )
        if query_resolution.status == "ambiguous":
            return MemoryContext(
                project_scope=project_scope, query_resolution=query_resolution,
                retrieval_status=RetrievalStatus(
                    router="router_failed" if route.status == "router_failed" else "forced",
                    router_available=route.status != "router_failed", warnings=["memory_reference_ambiguous"],
                ),
            )
        retrieval_query = query_resolution.query
    
        intent_keywords = self.retrieval.memory_intent_keywords(retrieval_query)
        deterministic_recall = self.retrieval.requires_personal_memory(retrieval_query)
        if route.status == "router_failed":
            router_state = "router_failed"
            should_retrieve = True
            router_keywords = self.retrieval.local_search_keywords(retrieval_query)
        elif route.status == "needed":
            router_state = "needed"
            should_retrieve = True
            router_keywords = route.keywords
        elif effective_project_id or project_scope.status == "ambiguous" or deterministic_recall or intent_keywords:
            router_state = "forced"
            should_retrieve = True
            router_keywords = self.retrieval.local_search_keywords(retrieval_query)
        else:
            return MemoryContext(
                retrieval_status=RetrievalStatus(router="not_needed"),
                project_scope=project_scope,
                query_resolution=query_resolution,
            )
    
        keywords = []
        for keyword in [*intent_keywords, *router_keywords]:
            normalized_keyword = " ".join(str(keyword or "").lower().split())
            if normalized_keyword and normalized_keyword not in keywords:
                keywords.append(normalized_keyword)
        logger.info(
            "Generated RAG Keywords: intent=%s router=%s combined=%s",
            intent_keywords,
            router_keywords,
            keywords,
        )
        if not keywords:
            keywords = self.retrieval.local_search_keywords(retrieval_query)
    
        if not should_retrieve:
            return MemoryContext(retrieval_status=RetrievalStatus(router="not_needed"))
    
        qdrant_results: list[dict] = []
        neo4j_results: list[str] = []
        qdrant_available = True
        neo4j_available = True
        include_historical = bool(_HISTORICAL_RE.search(user_message.lower()))
    
        remaining = max(deadline - time.monotonic(), 0.0)
        if remaining <= 0:
            future_qdrant = future_neo4j = None
            warnings.extend(["semantic_memory_timeout", "knowledge_graph_timeout"])
            diagnostics.append("The retrieval deadline was exhausted by routing and scope resolution.")
        else:
            completed: set[concurrent.futures.Future] = set()
            future_qdrant = self.retrieval_executor.submit(
                self.search_memory,
                retrieval_query,
                3,
                project_id=effective_project_id,
            )
            future_neo4j = self.retrieval_executor.submit(
                self.graph.search_knowledge,
                keywords,
                include_historical=include_historical,
                project_id=effective_project_id,
            )
            completed, _ = concurrent.futures.wait(
                (future_qdrant, future_neo4j),
                timeout=max(deadline - time.monotonic(), 0.0),
            )
        if future_qdrant is not None:
            if future_qdrant not in completed:
                qdrant_available = False
                warnings.append("semantic_memory_timeout")
                diagnostics.append(
                    "Qdrant semantic-memory retrieval exceeded "
                    f"{self.config.MEMORY_RETRIEVAL_TIMEOUT_SECONDS} seconds."
                )
                future_qdrant.cancel()
            else:
                try:
                    qdrant_results = future_qdrant.result()
                except Exception as exc:
                    qdrant_available = False
                    warnings.append("semantic_memory_unavailable")
                    diagnostics.append(traceback.format_exc())
                    logger.exception("Qdrant retrieval failed; continuing with remaining context: %s", exc)
    
        if future_neo4j is not None:
            if future_neo4j not in completed:
                neo4j_available = False
                warnings.append("knowledge_graph_timeout")
                diagnostics.append(
                    "Neo4j knowledge-graph retrieval exceeded "
                    f"{self.config.MEMORY_RETRIEVAL_TIMEOUT_SECONDS} seconds."
                )
                future_neo4j.cancel()
            else:
                try:
                    neo4j_results = future_neo4j.result()
                except Exception as exc:
                    neo4j_available = False
                    warnings.append("knowledge_graph_unavailable")
                    diagnostics.append(traceback.format_exc())
                    logger.exception("Neo4j retrieval failed; continuing with remaining context: %s", exc)
        else:
            neo4j_available = False
    
        qdrant_timed_out = future_qdrant is None
        if qdrant_timed_out:
            qdrant_available = False
    
        qdrant_results = self.filter_active_vector_memories(qdrant_results)
    
        if not qdrant_available and not neo4j_available:
            warnings.append("memory_backends_unavailable")
    
        if raise_on_error and diagnostics:
            raise InternalFeatureError(
                "memory_retrieval",
                "Pengambilan konteks memori gagal atau melewati batas waktu.",
                redact_diagnostic_log("\n\n".join(diagnostics)),
            )
    
        context = MemoryContext(
            qdrant_context=qdrant_results,
            neo4j_context=neo4j_results,
            retrieval_status=RetrievalStatus(
                router=router_state,
                router_available=router_state != "router_failed",
                qdrant_available=qdrant_available,
                neo4j_available=neo4j_available,
                degraded=not (qdrant_available and neo4j_available),
                warnings=warnings,
            ),
            project_scope=project_scope,
            query_resolution=query_resolution,
        )
        return context

    def filter_active_vector_memories(self, items: list[dict]) -> list[dict]:
        """Reject stale vectors even when an older Qdrant payload lacks lifecycle metadata."""
        if not items:
            return []
    
        message_ids = {str(item.get("message_id")) for item in items if item.get("message_id")}
        if not message_ids:
            return []
        db = self.persistence.open()
        try:
            active_ids = {
                str(row[0])
                for row in (
                    db.filter_active_vector_memories_active_ids(message_ids)
                )
            }
        finally:
            db.close()
        return [item for item in items if str(item.get("message_id") or "") in active_ids]
