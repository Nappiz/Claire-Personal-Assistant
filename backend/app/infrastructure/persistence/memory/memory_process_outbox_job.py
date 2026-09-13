from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class ProcessOutboxJobQueries:
    def process_memory_job_job(self, job_id):
        return (self.db.get(MemoryOutbox, job_id))

    def set_source_messages_memory_status_count(self, clean_ids, status):
        return (self.db.query(Message).filter(Message.id.in_(clean_ids)).update(
            {Message.memory_status: status}, synchronize_session=False
        ))
