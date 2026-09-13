from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class PersistInteractionQueries:
    def save_interaction_conversation(self, session_id):
        return (self.db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .with_for_update()
            .first())

    def save_interaction_msg_user(self, user_message_id):
        return (self.db.get(Message, user_message_id))

    def save_interaction_msg_user_after_claim(self, session_id, turn_id):
        return (self.db.query(Message)
                .filter(
                    Message.conversation_id == session_id,
                    Message.turn_id == turn_id,
                    Message.role == "user",
                )
                .first())

    def save_interaction_msg_ai(self, session_id, turn_id):
        return (self.db.query(Message)
                .filter(
                    Message.conversation_id == session_id,
                    Message.turn_id == turn_id,
                    Message.role == "assistant",
                )
                .first())

    def save_interaction_memory_job(self, turn_id):
        return (self.db.get(MemoryOutbox, turn_id))
