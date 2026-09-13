from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class CancelConversationJobsQueries:
    def cancel_memory_jobs_for_conversation_result(self, session_id):
        return (self.db.query(MemoryOutbox)
        .filter(
            MemoryOutbox.conversation_id == session_id,
            MemoryOutbox.status.in_(["pending", "processing", "failed"]),
        )
        .update(
            {
                MemoryOutbox.status: "cancelled",
                MemoryOutbox.next_retry_at: None,
                MemoryOutbox.last_error: "Source conversation deleted",
                MemoryOutbox.lease_token: None,
                MemoryOutbox.lease_expires_at: None,
            },
            synchronize_session=False,
        ))
