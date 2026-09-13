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

class ReindexVectors:
    def vector_reindex_snapshots(self, batch_size: int = 100):
        """Keyset scan: do not retain the entire archive or an open DB transaction."""
        cursor = ""
        while True:
            db = self.persistence.open()
            try:
                jobs = (
                    db.vector_reindex_snapshots_jobs(batch_size, cursor)
                )
                snapshots = [
                    {
                        "id": job.id, "conversation_id": job.conversation_id,
                        "message_id": job.user_message_id,
                        "extracted_knowledge": job.extracted_knowledge,
                        "stored_at": job.created_at.isoformat() if job.created_at else None,
                        "event_at": job.event_at.isoformat() if job.event_at else None,
                        "project_id": job.project_id,
                        "scope": job.scope or ("project" if job.project_id else "global"),
                    } for job in jobs
                ]
            finally:
                db.close()
            if not snapshots:
                return
            cursor = snapshots[-1]["id"]
            yield from snapshots

    def vector_source_is_active(self, item: dict) -> bool:
        db = self.persistence.open()
        try:
            return db.vector_source_is_active_result(item) is not None
        finally:
            db.close()

    def reindex_vector_memory_from_outbox(self) -> dict:
        """Reconcile durable event projections, never infer completeness from count."""
        indexed = 0
        failures = 0
        eligible = 0
        skipped = 0
        for item in self.vector_reindex_snapshots():
            eligible += 1
            try:
                if not self.vector_source_is_active(item):
                    skipped += 1
                    continue
                assertion_text, assertion_spans = self.assertion.vector_assertion_evidence(
                    item.get("extracted_knowledge")
                )
                if not assertion_text:
                    skipped += 1
                    continue
                changed = self.reconcile_memory(
                    assertion_text,
                    {
                        "session_id": item["conversation_id"],
                        "message_id": item["message_id"],
                        "memory_job_id": item["id"],
                        "source_role": "user",
                        "epistemic_status": "user_assertion",
                        "assertion_spans": assertion_spans,
                        "modality": "asserted_fact",
                        "polarity": "positive",
                        "stored_at": item["stored_at"],
                        "event_at": item["event_at"],
                        "project_id": item["project_id"],
                        "scope": item["scope"],
                        "memory_status": "active",
                    },
                    point_id=item["id"],
                )
                if not self.vector_source_is_active(item):
                    set_memories_status = self.vector.set_memories_status
                    set_memories_status([item["message_id"]], "inactive")
                    skipped += 1
                    continue
                indexed += int(changed)
                skipped += int(not changed)
            except Exception:
                failures += 1
                logger.exception("Could not reindex vector memory job %s", item["id"])
        return {"eligible": eligible, "indexed": indexed, "skipped": skipped, "failed": failures}
