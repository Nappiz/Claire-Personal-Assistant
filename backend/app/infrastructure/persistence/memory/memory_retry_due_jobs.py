from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class RetryDueJobsQueries:
    def process_due_memory_jobs_job_ids(self, legacy_lease_expired_at, now, safe_limit):
        return (self.db.query(MemoryOutbox.id)
            .filter(
                or_(
                    MemoryOutbox.status == "pending",
                    and_(
                        MemoryOutbox.status == "failed",
                        or_(MemoryOutbox.next_retry_at.is_(None), MemoryOutbox.next_retry_at <= now),
                    ),
                    and_(
                        MemoryOutbox.status == "processing",
                        or_(
                            MemoryOutbox.lease_expires_at <= now,
                            and_(
                                MemoryOutbox.lease_expires_at.is_(None),
                                MemoryOutbox.updated_at <= legacy_lease_expired_at,
                            ),
                        ),
                    ),
                )
            )
            .order_by(MemoryOutbox.created_at.asc())
            .limit(safe_limit)
            .all())

    def list_memory_jobs_jobs(self, safe_limit):
        return (self.db.query(MemoryOutbox)
            .order_by(MemoryOutbox.updated_at.desc())
            .limit(safe_limit)
            .all())

    def retry_memory_job_job(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))
