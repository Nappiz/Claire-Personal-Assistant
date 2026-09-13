from __future__ import annotations
import logging
from datetime import datetime, timezone
from app.domain.memory.contracts import TurnConflictError
logger = logging.getLogger("services.memory_service")

class BeginTurn:
    def begin_turn(self, session_id: str, user_message: str, turn_id: str) -> dict:
        """Persist and sequence a user turn before retrieval or provider I/O."""

        db = self.persistence.open()
        try:
            conversation = (
                db.begin_turn_conversation(session_id)
            )
            if conversation is None:
                raise ValueError("Session not found or has been deleted")
            previous_active_turn_id = conversation.active_turn_id

            existing_user = (
                db.begin_turn_existing_user_after_claim(session_id, turn_id)
            )
            existing_assistant = (
                db.begin_turn_existing_assistant_after_claim(session_id, turn_id)
            )
            if existing_user is not None and existing_user.content != user_message:
                raise TurnConflictError("turn_id was already used for different content")
            if existing_assistant is not None and existing_assistant.message_type == "normal":
                return {
                    "turn_id": turn_id,
                    "turn_sequence": existing_assistant.turn_sequence,
                    "user_message_id": str(existing_user.id) if existing_user else None,
                    "cached_reply": existing_assistant.content,
                    "completed": True,
                    "response_status": existing_assistant.response_status or "complete",
                    "finish_reason": existing_assistant.finish_reason,
                }
            claimed = db.begin_turn_claimed(session_id, turn_id)
            if claimed.rowcount != 1:
                raise TurnConflictError("Another turn is already active for this conversation")
            if previous_active_turn_id and previous_active_turn_id != turn_id:
                db.begin_turn_update(previous_active_turn_id, session_id)
            db.expire_all()
            conversation = db.begin_turn_conversation_after_claim(session_id)
            existing_user = (
                db.begin_turn_existing_user_after_claim(session_id, turn_id)
            )
            existing_assistant = (
                db.begin_turn_existing_assistant_after_claim(session_id, turn_id)
            )
            if existing_assistant is not None and existing_assistant.message_type == "normal":
                conversation.active_turn_id = None
                conversation.active_turn_expires_at = None
                db.commit()
                return {
                    "turn_id": turn_id,
                    "turn_sequence": existing_assistant.turn_sequence,
                    "user_message_id": str(existing_user.id) if existing_user else None,
                    "cached_reply": existing_assistant.content,
                    "completed": True,
                    "response_status": existing_assistant.response_status or "complete",
                    "finish_reason": existing_assistant.finish_reason,
                }

            if existing_user is None:
                sequence = int(conversation.next_turn_sequence or 1)
                existing_user = db.new_message(
                    conversation_id=session_id,
                    role="user",
                    content=user_message,
                    message_type="pending_turn",
                    turn_id=turn_id,
                    turn_sequence=sequence,
                )
                db.add(existing_user)
                conversation.next_turn_sequence = sequence + 1
                conversation.message_count = int(conversation.message_count or 0) + 1
            else:
                sequence = int(existing_user.turn_sequence or conversation.next_turn_sequence or 1)
                existing_user.turn_sequence = sequence
                existing_user.message_type = "pending_turn"
                conversation.next_turn_sequence = max(int(conversation.next_turn_sequence or 1), sequence + 1)

            conversation.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing_user)
            return {
                "turn_id": turn_id,
                "turn_sequence": sequence,
                "user_message_id": str(existing_user.id),
                "cached_reply": None,
                "completed": False,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
