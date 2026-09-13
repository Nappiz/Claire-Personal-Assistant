from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class RetrieveContextQueries:
    def filter_active_vector_memories_active_ids(self, message_ids):
        return (self.db.query(Message.id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .filter(
                    Message.id.in_(message_ids),
                    Message.role == "user",
                    Message.message_type == "normal",
                    Message.memory_status == "active",
                    Conversation.deleted_at.is_(None),
                )
                .all())
