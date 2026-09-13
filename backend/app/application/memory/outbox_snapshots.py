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

class OutboxSnapshots:
    def get_memory_job_snapshot(self, job_id: str, lease_token: str | None = None) -> dict | None:
    
        db = self.persistence.open()
        try:
            job = db.get_memory_job_snapshot_job(job_id)
            if not job or (lease_token is not None and job.lease_token != lease_token):
                return None
            return {
                "id": job.id,
                "conversation_id": job.conversation_id,
                "user_message_id": job.user_message_id,
                "user_message": job.user_message,
                "assistant_response": job.assistant_response,
                "session_history": list(job.session_history or []),
                "neo4j_context": list(job.neo4j_context or []),
                "extracted_knowledge": job.extracted_knowledge,
                "project_id": job.project_id,
                "project_name": job.project_name,
                "scope": job.scope or "global",
                "vector_saved": bool(job.vector_saved),
                "extraction_completed": bool(job.extraction_completed),
                "graph_saved": bool(job.graph_saved),
                "status": job.status,
                "attempts": job.attempts,
                "created_at": job.created_at,
                "event_at": job.event_at or job.created_at,
                "lease_token": job.lease_token,
            }
        finally:
            db.close()

    def update_memory_job(self, job_id: str, *, expected_lease_token: str | None = None, **updates) -> dict | None:
    
        db = self.persistence.open()
        try:
            if expected_lease_token is not None and hasattr(db, "execute"):
                result = db.update_memory_job_result(expected_lease_token, job_id, updates)
                db.commit()
                if result != 1:
                    return None
                job = db.update_memory_job_job_after_claim(job_id)
                return self.outbox.outbox_job_data(job) if job else None
            job = db.update_memory_job_job_after_claim(job_id)
            if not job or (expected_lease_token is not None and job.lease_token != expected_lease_token):
                return None
            for field, value in updates.items():
                setattr(job, field, value)
            db.commit()
            db.refresh(job)
            return self.outbox.outbox_job_data(job)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def memory_job_is_active(self, job_id: str, lease_token: str) -> bool:
        """Stop workers that race with a user deleting the source conversation."""
    
        db = self.persistence.open()
        try:
            job = db.memory_job_is_active_job(job_id, lease_token)
            if (
                not job
                or job.lease_token != lease_token
                or job.status != "processing"
                or not job.lease_expires_at
            ):
                return False
            lease_expires_at = job.lease_expires_at
            if lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
            if lease_expires_at <= datetime.now(timezone.utc):
                return False
            return (
                db.memory_job_is_active_result(job)
                is not None
            )
        finally:
            db.close()

    def conversation_is_deleted(self, conversation_id: str) -> bool:
    
        db = self.persistence.open()
        try:
            conversation = db.conversation_is_deleted_conversation(conversation_id)
            return conversation is None or conversation.deleted_at is not None
        finally:
            db.close()

    def leased_memory_job_snapshot(self, job_id: str, lease_token: str) -> dict | None:
        """Small adapter retained for simple test doubles while enforcing leases in production."""
        try:
            return self.get_memory_job_snapshot(job_id, lease_token)
        except TypeError:
            return self.get_memory_job_snapshot(job_id)
