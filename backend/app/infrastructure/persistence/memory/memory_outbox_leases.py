from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class OutboxLeasesQueries:
    def claim_memory_job_job(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def claim_memory_job_result(self, job_id, legacy_lease_expired_at, now, token):
        eligible = or_(
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
        return (self.db.execute(
            update(MemoryOutbox)
            .where(MemoryOutbox.id == job_id, eligible)
            .values(
                status="processing",
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS),
                attempts=MemoryOutbox.attempts + 1,
                last_error=None,
                updated_at=now,
            )
        ))

    def finish_memory_job_job(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def finish_memory_job_changed(self, job_id, lease_token, updates):
        return (self.db.query(MemoryOutbox).filter(
            MemoryOutbox.id == job_id,
            MemoryOutbox.lease_token == lease_token,
        ).update(updates, synchronize_session=False))

    def finish_memory_job_current(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def finish_memory_job_current_after_claim(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))
