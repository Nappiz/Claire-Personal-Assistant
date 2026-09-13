from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class CompleteTurnQueries:
    def mark_turn_status_message(self, session_id, turn_id):
        return (self.db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            )
            .first())

    def mark_turn_status_conversation(self, session_id):
        return (self.db.get(Conversation, session_id))
