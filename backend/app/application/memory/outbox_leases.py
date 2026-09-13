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

class OutboxLeases:
    def claim_memory_job(self, job_id: str) -> str | None:
        """Atomically acquire one due job; a stale worker cannot finalize this lease."""
    
        now = datetime.now(timezone.utc)
        legacy_lease_expired_at = now - timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS)
        token = str(uuid.uuid4())
        db = self.persistence.open()
        try:
            if not hasattr(db, "execute"):
                job = db.claim_memory_job_job(job_id)
                if not job or job.status in {"completed", "cancelled"}:
                    return None
                job.status = "processing"
                job.lease_token = token
                job.lease_expires_at = now + timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS)
                job.attempts += 1
                job.last_error = None
                db.commit()
                return token
            result = db.claim_memory_job_result(job_id, legacy_lease_expired_at, now, token)
            db.commit()
            return token if result.rowcount == 1 else None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def finish_memory_job(self, job_id: str, lease_token: str, stage_errors: list[str]) -> dict | None:
        """Persist a retryable final state after one independent stage pass."""
    
        db = self.persistence.open()
        try:
            job = db.finish_memory_job_current_after_claim(job_id)
            if not job or job.status == "cancelled" or job.lease_token != lease_token:
                return self.outbox.outbox_job_data(job) if job else None
    
            updates = self.outbox.finalize_updates(job, stage_errors)
            changed = db.finish_memory_job_changed(job_id, lease_token, updates)
            db.commit()
            if changed != 1:
                current = db.finish_memory_job_current_after_claim(job_id)
                return self.outbox.outbox_job_data(current) if current else None
            current = db.finish_memory_job_current_after_claim(job_id)
            return self.outbox.outbox_job_data(current) if current else None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def cancel_claim(self, job_id: str, lease_token: str, reason: str) -> dict | None:
        return self.update_memory_job(
            job_id,
            expected_lease_token=lease_token,
            status="cancelled",
            next_retry_at=None,
            lease_token=None,
            lease_expires_at=None,
            last_error=reason,
        )
