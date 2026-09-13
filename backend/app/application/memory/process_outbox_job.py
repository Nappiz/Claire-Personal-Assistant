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

class ProcessOutboxJob:
    def process_memory_job(self, job_id: str, *, report_errors: bool = False) -> dict | None:
        """Attempt every unfinished memory stage without coupling their failures.

    SQLite is the durable source of truth for this job. Qdrant and Neo4j are
    independent stores, so a failed vector upsert must not prevent extraction
    and graph persistence, and vice versa. The same job ID is reused as the
    Qdrant point ID, making a retry idempotent for the vector stage.
    """
        lease_token = self.claim_memory_job(job_id)
        if lease_token is None:
            db = self.persistence.open()
            try:
                job = db.process_memory_job_job(job_id)
                return self.outbox.outbox_job_data(job) if job else None
            finally:
                db.close()
    
        snapshot = self.leased_memory_job_snapshot(job_id, lease_token)
        if not snapshot or not self.memory_job_is_active(job_id, lease_token):
            return self.cancel_claim(job_id, lease_token, "Source conversation is deleted or lease was lost")
    
        stage_errors: list[str] = []
        reportable_error_logs: list[str] = []
        reportable_operation: str | None = None
    
        def finish_result() -> dict | None:
            result = self.finish_memory_job(job_id, lease_token, stage_errors)
            if report_errors and reportable_error_logs:
                result = dict(result or {})
                result["reportable_operation"] = reportable_operation or "memory_pipeline"
                result["reportable_error_log"] = redact_diagnostic_log(
                    "\n\n".join(reportable_error_logs)
                )
            return result
    
        # Validate extraction first in a user-facing strict run. This prevents a
        # malformed extractor result from being written to another memory store.
        if not snapshot["extraction_completed"]:
            try:
                with self.usage_context(conversation_id=snapshot["conversation_id"], turn_id=job_id,
                                   job_id=job_id, job_attempt=snapshot.get("attempts")):
                    extracted_data = self.extract_knowledge(
                        snapshot["user_message"],
                        neo4j_context=snapshot["neo4j_context"],
                        session_history=snapshot["session_history"],
                        raise_on_error=True,
                        project_id=snapshot.get("project_id"),
                        project_name=snapshot.get("project_name"),
                        event_at=snapshot.get("event_at"),
                    )
                self.update_memory_job(
                    job_id,
                    expected_lease_token=lease_token,
                    extracted_knowledge=extracted_data,
                    extraction_completed=True,
                )
            except Exception as exc:
                logger.exception("Memory job %s failed during knowledge extraction", job_id)
                stage_errors.append(f"extraction: {exc}")
                if report_errors and not isinstance(exc, MemoryLLMUnavailableError):
                    reportable_operation = reportable_operation or "knowledge_extraction"
                    reportable_error_logs.append(traceback.format_exc())
    
        if report_errors and reportable_error_logs:
            return finish_result()
    
        snapshot = self.leased_memory_job_snapshot(job_id, lease_token)
        if not snapshot or not self.memory_job_is_active(job_id, lease_token):
            return self.cancel_claim(job_id, lease_token, "Source conversation is deleted or lease was lost")
    
        if (
            snapshot["extraction_completed"]
            and not snapshot["vector_saved"]
            and self.memory_job_is_active(job_id, lease_token)
        ):
            try:
                assertion_text, assertion_spans = self.assertion.vector_assertion_evidence(
                    snapshot.get("extracted_knowledge")
                )
                if assertion_text:
                    self.save_memory(
                        assertion_text,
                        {
                            "session_id": snapshot["conversation_id"],
                            "message_id": snapshot["user_message_id"],
                            "memory_job_id": job_id,
                            "source_role": "user",
                            "epistemic_status": "user_assertion",
                            "assertion_spans": assertion_spans,
                            "modality": "asserted_fact",
                            "polarity": "positive",
                            "stored_at": snapshot["created_at"].isoformat() if snapshot.get("created_at") else None,
                            "event_at": snapshot["event_at"].isoformat() if snapshot.get("event_at") else None,
                            "memory_status": "active",
                            "project_id": snapshot.get("project_id"),
                            "scope": snapshot.get("scope") or "global",
                        },
                        point_id=job_id,
                    )
                else:
                    logger.info("Memory job %s has no positive assertion for vector indexing", job_id)
                if not self.memory_job_is_active(job_id, lease_token):
                    if self.conversation_is_deleted(snapshot["conversation_id"]):
                        self.compensate_deleted_conversation(snapshot)
                    return self.cancel_claim(job_id, lease_token, "Conversation deleted during vector write")
                self.update_memory_job(job_id, expected_lease_token=lease_token, vector_saved=True)
            except Exception as exc:
                logger.exception("Memory job %s failed during Qdrant upsert", job_id)
                stage_errors.append(f"vector: {exc}")
                if report_errors:
                    reportable_operation = reportable_operation or "vector_memory_write"
                    reportable_error_logs.append(traceback.format_exc())
    
        if report_errors and reportable_error_logs:
            return finish_result()
    
        snapshot = self.leased_memory_job_snapshot(job_id, lease_token)
        if not snapshot or not self.memory_job_is_active(job_id, lease_token):
            return self.cancel_claim(job_id, lease_token, "Source conversation is deleted or lease was lost")
    
        if snapshot["extraction_completed"] and not snapshot["graph_saved"]:
            try:
                extracted_data = snapshot["extracted_knowledge"] or {"nodes": [], "edges": [], "retractions": []}
                nodes = extracted_data.get("nodes", [])
                edges = extracted_data.get("edges", [])
                retractions = extracted_data.get("retractions", [])
                graph_result = {}
                if nodes or edges or retractions:
                    graph_result = self.graph.merge_knowledge(
                        nodes,
                        edges,
                        retractions=retractions,
                        source_conversation_id=snapshot["conversation_id"],
                        source_message_id=snapshot["user_message_id"],
                        project_id=snapshot.get("project_id"),
                        project_name=snapshot.get("project_name"),
                        event_id=job_id,
                        event_at=snapshot.get("event_at"),
                    )
                if not self.memory_job_is_active(job_id, lease_token):
                    if self.conversation_is_deleted(snapshot["conversation_id"]):
                        self.compensate_deleted_conversation(snapshot)
                    return self.cancel_claim(job_id, lease_token, "Conversation deleted during graph write")
                invalidated_ids = list((graph_result or {}).get("invalidated_source_message_ids") or [])
                if invalidated_ids:
                    set_memories_status = self.vector.set_memories_status
    
                    self.set_source_messages_memory_status(invalidated_ids, "inactive")
                    set_memories_status(
                        invalidated_ids,
                        status="inactive",
                        event_at=snapshot.get("event_at"),
                    )
                self.update_memory_job(job_id, expected_lease_token=lease_token, graph_saved=True)
            except Exception as exc:
                logger.exception("Memory job %s failed during Neo4j merge", job_id)
                stage_errors.append(f"graph: {exc}")
                if report_errors:
                    reportable_operation = reportable_operation or "knowledge_graph_write"
                    reportable_error_logs.append(traceback.format_exc())
    
        return finish_result()

    def compensate_deleted_conversation(self, snapshot: dict) -> None:
        """Remove writes that crossed a deletion tombstone after an external call began."""
        delete_memory_by_session = self.vector.delete_memory_by_session
    
        errors: list[Exception] = []
        for operation in (
            lambda: delete_memory_by_session(snapshot["conversation_id"]),
            lambda: self.graph.remove_conversation_provenance(
                snapshot["conversation_id"], [snapshot["user_message_id"]]
            ),
        ):
            try:
                operation()
            except Exception as exc:
                errors.append(exc)
                logger.exception("Compensating memory cleanup failed")
        if errors:
            raise RuntimeError("Conversation was deleted and compensating cleanup was incomplete")

    def set_source_messages_memory_status(self, message_ids: list[str], status: str) -> int:
        if status not in {"active", "inactive"}:
            raise ValueError("Unsupported memory status")
        clean_ids = {str(item) for item in message_ids if item}
        if not clean_ids:
            return 0
    
        db = self.persistence.open()
        try:
            count = db.set_source_messages_memory_status_count(clean_ids, status)
            db.commit()
            return count
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
