from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from app.domain.memory.contracts import MEMORY_RETRY_BASE_SECONDS, MEMORY_RETRY_MAX_SECONDS
logger = logging.getLogger("services.memory_service")

class OutboxPolicy:
    def __init__(self, config):
        self.config = config

    def outbox_job_data(self, job: Any) -> dict:
        """Return only operational metadata; never expose chat payload by default."""
        return {
            "id": job.id,
            "conversation_id": job.conversation_id,
            "user_message_id": job.user_message_id,
            "status": job.status,
            "vector_saved": bool(job.vector_saved),
            "extraction_completed": bool(job.extraction_completed),
            "graph_saved": bool(job.graph_saved),
            "attempts": job.attempts,
            "last_error": job.last_error,
            "next_retry_at": job.next_retry_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    def finalize_updates(self, job, stage_errors: list[str]) -> dict:
        if job.vector_saved and job.extraction_completed and job.graph_saved:
            updates = {
                "status": "completed",
                "last_error": None,
                "next_retry_at": None,
                "completed_at": datetime.now(timezone.utc),
                "lease_token": None,
                "lease_expires_at": None,
            }
        else:
            delay_seconds = min(
                MEMORY_RETRY_BASE_SECONDS * (2 ** max(job.attempts - 1, 0)),
                MEMORY_RETRY_MAX_SECONDS,
            )
            updates = {
                "status": "failed",
                "last_error": " | ".join(stage_errors)[:4000] or "Memory job did not complete all stages",
                "next_retry_at": datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
                "lease_token": None,
                "lease_expires_at": None,
            }
        return updates
