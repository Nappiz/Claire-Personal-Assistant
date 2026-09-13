from models.conversation import Conversation


class SQLAlchemyConversationRepository:
    def __init__(self, db):
        self.db = db

    def get(self, session_id, *, active_only=False):
        if not active_only:
            return self.db.get(Conversation, session_id)
        return self.db.query(Conversation).filter(
            Conversation.id == session_id, Conversation.deleted_at.is_(None),
        ).first()

    def list(self):
        return self.db.query(Conversation).filter(Conversation.deleted_at.is_(None)).order_by(
            Conversation.is_pinned.desc(), Conversation.pinned_at.desc(), Conversation.updated_at.desc(),
        ).all()

    def new(self, **values):
        conversation = Conversation(**values)
        self.db.add(conversation)
        return conversation
