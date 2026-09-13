from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class RecordInternalErrorQueries:
    def record_internal_error_user_row(self, user_message_id):
        return (self.db.get(Message, user_message_id))

    def record_internal_error_assistant_row(self, assistant_message_id):
        return (self.db.get(Message, assistant_message_id))

    def record_internal_error_user_row_after_claim(self, session_id, turn_id):
        return (self.db.query(Message).filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            ).first())

    def record_internal_error_assistant_row_after_claim(self, session_id, turn_id):
        return (self.db.query(Message).filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "assistant",
            ).first())

    def record_internal_error_recent_user(self, recent_cutoff, session_id, user_message):
        return (self.db.query(Message)
                .filter(
                    Message.conversation_id == session_id,
                    Message.role == "user",
                    Message.message_type == "normal",
                    Message.content == user_message,
                    Message.created_at >= recent_cutoff,
                )
                .order_by(Message.created_at.desc())
                .first())

    def record_internal_error_recent_assistant(self, recent_user, session_id):
        return (self.db.query(Message)
                    .filter(
                        Message.conversation_id == session_id,
                        Message.role == "assistant",
                        Message.message_type == "normal",
                        Message.created_at >= recent_user.created_at,
                    )
                    .order_by(Message.created_at.desc())
                    .first())

    def record_internal_error_memory_job(self, memory_job_id):
        return (self.db.get(MemoryOutbox, memory_job_id))

    def record_internal_error_conversation(self, session_id):
        return (self.db.get(Conversation, session_id))

    def record_internal_error_conversation_after_claim(self, session_id):
        return (self.db.get(Conversation, session_id))
