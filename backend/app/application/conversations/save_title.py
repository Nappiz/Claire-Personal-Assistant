from __future__ import annotations
import logging
logger = logging.getLogger("services.memory_service")

class SaveTitle:
    def generate_and_save_title(self, session_id: str, first_message: str):
        """
    Fungsi background task untuk men-generate judul sesi dan menyimpannya ke SQLite.
    """
        try:
            db = self.persistence.open()
            try:
                with self.usage_context(conversation_id=session_id, turn_id=None, job_id=None, job_attempt=None):
                    title = self.generate_session_title(first_message)

                conv = db.generate_and_save_title_conv(session_id)
                if conv:
                    conv.title = title
                    db.commit()
                    logger.info(f" -> Session title updated to: '{title}'")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in background task generate_and_save_title: {e}")
