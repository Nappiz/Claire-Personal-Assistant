from models.conversation import Conversation

class SaveTitleQueries:
    def generate_and_save_title_conv(self, session_id):
        return (self.db.query(Conversation).filter(
                Conversation.id == session_id,
                Conversation.deleted_at.is_(None),
            ).first())
