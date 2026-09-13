from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class ReadHistoryQueries:
    def get_session_history_messages(self, limit, session_id):
        return (self.db.query(Message)
        .filter(
            Message.conversation_id == session_id,
            Message.message_type == "normal",
        )
        .order_by(*Message.chronological_order(descending=True))
        .limit(limit)
        .all())

    def get_session_summary_row(self, session_id):
        return (self.db.query(Conversation.summary).filter(Conversation.id == session_id).first())
