from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class BeginTurnQueries:
    def begin_turn_conversation(self, session_id):
        return (self.db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .with_for_update()
            .first())

    def begin_turn_existing_user(self, session_id, turn_id):
        return (self.db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            )
            .first())

    def begin_turn_existing_assistant(self, session_id, turn_id):
        return (self.db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "assistant",
            )
            .first())

    def begin_turn_claimed(self, session_id, turn_id):
        return (self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == session_id,
                Conversation.deleted_at.is_(None),
                or_(
                    Conversation.active_turn_id.is_(None),
                    Conversation.active_turn_id == turn_id,
                    Conversation.active_turn_expires_at.is_(None),
                    Conversation.active_turn_expires_at <= datetime.now(timezone.utc),
                ),
            )
            .values(
                active_turn_id=turn_id,
                active_turn_expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=max(int(self.config.TURN_LEASE_SECONDS), 60)),
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        ))

    def begin_turn_update(self, previous_active_turn_id, session_id):
        return (self.db.query(Message).filter(
                Message.conversation_id == session_id,
                Message.turn_id == previous_active_turn_id,
                Message.role == "user",
                Message.message_type == "pending_turn",
            ).update(
                {Message.message_type: "interrupted_turn"},
                synchronize_session=False,
            ))

    def begin_turn_conversation_after_claim(self, session_id):
        return (self.db.get(Conversation, session_id))

    def begin_turn_existing_user_after_claim(self, session_id, turn_id):
        return (self.db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            )
            .first())

    def begin_turn_existing_assistant_after_claim(self, session_id, turn_id):
        return (self.db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "assistant",
            )
            .first())
