from models.memory_outbox import MemoryOutbox


class SQLAlchemyMemoryJobRepository:
    """Persistence primitives; lease/retry decisions remain in the stage-6 bridge."""
    def __init__(self, db):
        self.db = db

    def get(self, job_id):
        return self.db.get(MemoryOutbox, job_id)

    def recent(self, limit=50):
        return self.db.query(MemoryOutbox).order_by(MemoryOutbox.created_at.desc()).limit(min(max(int(limit), 1), 100)).all()

    def delete_for_conversation(self, session_id):
        self.db.query(MemoryOutbox).filter(MemoryOutbox.conversation_id == session_id).delete()
