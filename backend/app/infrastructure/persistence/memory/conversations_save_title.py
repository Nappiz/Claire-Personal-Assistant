from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class SaveTitleQueries:
    def generate_and_save_title_conv(self, session_id):
        return (self.db.query(Conversation).filter(
                Conversation.id == session_id,
                Conversation.deleted_at.is_(None),
            ).first())
