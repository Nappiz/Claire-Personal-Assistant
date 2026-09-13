from models.message import Message


class SQLAlchemyMessageRepository:
    def __init__(self, db):
        self.db = db

    def history(self, session_id):
        return self.db.query(Message).filter(Message.conversation_id == session_id).order_by(*Message.chronological_order()).all()

    def delete_for_conversation(self, session_id):
        self.db.query(Message).filter(Message.conversation_id == session_id).delete()
