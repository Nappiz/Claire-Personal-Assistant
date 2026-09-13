from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class OutboxSnapshotsQueries:
    def get_memory_job_snapshot_job(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def update_memory_job_result(self, expected_lease_token, job_id, updates):
        return (self.db.query(MemoryOutbox).filter(
                MemoryOutbox.id == job_id,
                MemoryOutbox.lease_token == expected_lease_token,
            ).update(updates, synchronize_session=False))

    def update_memory_job_job(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def update_memory_job_job_after_claim(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def memory_job_is_active_job(self, job_id, lease_token):
        return (self.db.query(MemoryOutbox).filter(
            MemoryOutbox.id == job_id,
            MemoryOutbox.lease_token == lease_token,
        ).first())

    def memory_job_is_active_result(self, job):
        return (self.db.query(Conversation.id)
            .filter(
                Conversation.id == job.conversation_id,
                Conversation.deleted_at.is_(None),
            )
            .first())

    def conversation_is_deleted_conversation(self, conversation_id):
        return (self.db.get(Conversation, conversation_id))
