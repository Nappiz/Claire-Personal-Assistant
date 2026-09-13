from __future__ import annotations
import logging
from typing import Any
logger = logging.getLogger("services.memory_service")

class ReadHistory:
    def get_session_history(self, db: Any, session_id: str, limit: int = 30):
        """
    Mengambil N pesan terakhir dari sebuah sesi (Short-Term Memory).
    """
        db = self.persistence.wrap(db)
        if not session_id:
            return []

        messages = (
            db.get_session_history_messages(limit, session_id)
        )

        history = []
        for msg in reversed(messages):
            history.append({"role": msg.role, "content": msg.content})

        return history

    def get_session_summary(self, db: Any, session_id: str) -> str:
        db = self.persistence.wrap(db)
        if not session_id:
            return ""
        row = db.get_session_summary_row(session_id)
        return str(row[0] or "") if row else ""
