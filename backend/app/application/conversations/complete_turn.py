from __future__ import annotations
import logging
logger = logging.getLogger("services.memory_service")

class CompleteTurn:
    def mark_turn_status(self, session_id: str, turn_id: str, status: str, details: dict | None = None) -> None:
        """Release a turn lease while keeping its durable user message retryable."""
    
        if status not in {"interrupted_turn", "failed_turn", "pending_turn"}:
            raise ValueError("Unsupported turn status")
        db = self.persistence.open()
        try:
            message = (
                db.mark_turn_status_message(session_id, turn_id)
            )
            conversation = db.mark_turn_status_conversation(session_id)
            if message and message.message_type != "normal":
                message.message_type = status
                message.error_details = details
            if conversation and conversation.active_turn_id == turn_id:
                conversation.active_turn_id = None
                conversation.active_turn_expires_at = None
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
