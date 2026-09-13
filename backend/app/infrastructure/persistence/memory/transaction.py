from app.infrastructure.persistence.memory.memory_resolve_project_scope import ResolveProjectScopeQueries
from app.infrastructure.persistence.memory.memory_retrieve_context import RetrieveContextQueries
from app.infrastructure.persistence.memory.conversations_read_history import ReadHistoryQueries
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.llm_usage import LLMUsageLog


class MemoryTransaction(ResolveProjectScopeQueries, RetrieveContextQueries, ReadHistoryQueries):
    """SQLAlchemy-backed UOW; query capabilities stay in focused adapter mixins."""
    def __init__(self, db, config):
        self.db, self.config = db, config

    def __getattr__(self, name):
        # Preserve legacy test-double execute capability checks, not an app API.
        return getattr(self.db, name)

    def new_message(self, **values): return Message(**values)
    def new_conversation(self, **values): return Conversation(**values)
    def new_outbox(self, **values): return MemoryOutbox(**values)
    def new_usage(self, **values): return LLMUsageLog(**values)
    def add(self, record): return self.db.add(record)
    def commit(self): return self.db.commit()
    def rollback(self): return self.db.rollback()
    def refresh(self, record): return self.db.refresh(record)
    def flush(self): return self.db.flush()
    def expire_all(self): return self.db.expire_all()
    def close(self): return self.db.close()


class SQLAlchemyMemoryPersistence:
    def __init__(self, config): self.config = config

    def open(self):
        from configs.database import SessionLocal
        return self.wrap(SessionLocal())

    def wrap(self, db):
        return db if isinstance(db, MemoryTransaction) else MemoryTransaction(db, self.config)
