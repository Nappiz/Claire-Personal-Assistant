from models.message import Message
from models.conversation import Conversation

class ReadHistoryQueries:
    def get_session_history_messages(self, limit, session_id):
        return (self.db.query(Message)
        .filter(
            Message.conversation_id == session_id,
            Message.message_type == "normal",
        )
        .order_by(*Message.chronological_order(descending=True))
        .limit(limit)
        .all())

    def get_session_summary_row(self, session_id):
        return (self.db.query(Conversation.summary).filter(Conversation.id == session_id).first())
