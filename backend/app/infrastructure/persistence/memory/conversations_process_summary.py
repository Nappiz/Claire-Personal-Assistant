from models.message import Message
from models.conversation import Conversation

class ProcessSummaryQueries:
    def process_conversation_summary_conversation(self, session_id):
        return (self.db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .first())

    def process_conversation_summary_rows(self, checkpoint, session_id):
        return (self.db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.message_type == "normal",
                Message.turn_sequence.is_not(None),
                Message.turn_sequence > checkpoint,
            )
            .order_by(*Message.chronological_order())
            .all())

    def process_conversation_summary_update(self, expected_next_sequence, session_id, version):
        return (self.db.query(Conversation).filter(
                Conversation.id == session_id,
                Conversation.summary_version == version,
                Conversation.next_turn_sequence == expected_next_sequence,
                Conversation.deleted_at.is_(None),
            ).update({Conversation.summary_pending: False}, synchronize_session=False))

    def process_conversation_summary_result(self, checkpoint, expected_next_sequence, fold_through, session_id, updated_summary, version):
        return (self.db.query(Conversation).filter(
            Conversation.id == session_id,
            Conversation.summary_version == version,
            Conversation.summary_through_sequence == checkpoint,
            Conversation.next_turn_sequence == expected_next_sequence,
            Conversation.deleted_at.is_(None),
        ).update(
            {
                Conversation.summary: updated_summary,
                Conversation.summary_version: version + 1,
                Conversation.summary_through_sequence: fold_through,
                Conversation.summary_pending: False,
            },
            synchronize_session=False,
        ))

    def process_due_summaries_ids(self, limit):
        return (self.db.query(Conversation.id)
            .filter(Conversation.summary_pending.is_(True), Conversation.deleted_at.is_(None))
            .order_by(Conversation.updated_at.asc())
            .limit(min(max(int(limit), 1), 100))
            .all())
