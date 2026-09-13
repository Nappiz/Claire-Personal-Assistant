from __future__ import annotations
import logging
from typing import Any
logger = logging.getLogger("services.memory_service")

class CancelConversationJobs:
    def cancel_memory_jobs_for_conversation(self, session_id: str, db: Any) -> int:
        """Prevent queued work from recreating memory after a session is deleted."""
        db = self.persistence.wrap(db)
        return (
            db.cancel_memory_jobs_for_conversation_result(session_id)
        )
