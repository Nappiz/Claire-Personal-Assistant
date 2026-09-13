from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class ReindexVectorsQueries:
    def vector_reindex_snapshots_jobs(self, batch_size, cursor):
        return (self.db.query(MemoryOutbox)
                .join(Conversation, Conversation.id == MemoryOutbox.conversation_id)
                .join(Message, Message.id == MemoryOutbox.user_message_id)
                .filter(
                    MemoryOutbox.id > cursor,
                    MemoryOutbox.status != "cancelled",
                    MemoryOutbox.extraction_completed.is_(True),
                    Conversation.deleted_at.is_(None),
                    Message.memory_status == "active",
                )
                .order_by(MemoryOutbox.id.asc())
                .limit(batch_size)
                .all())

    def vector_source_is_active_result(self, item):
        return (self.db.query(Conversation.id).join(
            Message, Message.conversation_id == Conversation.id
        ).filter(
            Conversation.id == item["conversation_id"],
            Conversation.deleted_at.is_(None),
            Message.id == item["message_id"],
            Message.memory_status == "active",
        ).first())
