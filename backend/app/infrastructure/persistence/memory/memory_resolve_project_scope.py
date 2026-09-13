from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, update
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from models.llm_usage import LLMUsageLog
from app.domain.memory.contracts import _MEMORY_JOB_LEASE_SECONDS

class ResolveProjectScopeQueries:
    def resolve_project_scope_projects(self):
        return (self.db.query(Project).order_by(Project.updated_at.desc()).all())
