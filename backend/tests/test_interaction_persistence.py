"""Regression coverage for ORM identifiers returned after committing a chat turn."""

from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base
from models.conversation import Conversation
from models.message import Message
from schemas.chat_sch import MemoryContext
from services import memory_service


class InteractionPersistenceTests(TestCase):
    def test_save_interaction_returns_plain_ids_after_expiring_commit(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        test_session = sessionmaker(bind=engine, expire_on_commit=True)

        db = test_session()
        conversation = Conversation(title="Test")
        db.add(conversation)
        db.flush()
        session_id = str(conversation.id)
        db.commit()
        db.close()

        with (
            patch.object(memory_service, "SessionLocal", test_session, create=True),
            patch("configs.database.SessionLocal", test_session),
            patch.object(
                memory_service,
                "process_memory_job",
                return_value={"status": "completed"},
            ),
        ):
            result = memory_service.save_interaction(
                session_id=session_id,
                user_message="Halo",
                ai_response="Hai",
                usage={},
                context=MemoryContext(),
            )

        self.assertIsInstance(result["user_message_id"], str)
        self.assertIsInstance(result["assistant_message_id"], str)
        self.assertIsInstance(result["memory_job_id"], str)

        verification_db = test_session()
        try:
            self.assertEqual(
                2,
                verification_db.query(Message)
                .filter(Message.conversation_id == session_id)
                .count(),
            )
        finally:
            verification_db.close()

    def test_error_recorder_reuses_recent_committed_pair_when_ids_are_missing(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        test_session = sessionmaker(bind=engine, expire_on_commit=True)

        db = test_session()
        conversation = Conversation(title="Test")
        db.add(conversation)
        db.flush()
        session_id = str(conversation.id)
        db.add_all(
            [
                Message(conversation_id=session_id, role="user", content="Halo"),
                Message(conversation_id=session_id, role="assistant", content="Jawaban sementara"),
            ]
        )
        db.commit()
        db.close()

        with patch("configs.database.SessionLocal", test_session):
            memory_service.record_internal_error(
                session_id=session_id,
                user_message="Halo",
                analysis="Penyimpanan gagal dianalisis.",
                error_details={
                    "code": "INTERNAL_FEATURE_ERROR",
                    "operation": "chat_persistence",
                    "message": "Penyimpanan gagal",
                    "analysis": "Penyimpanan gagal dianalisis.",
                    "log": "Traceback",
                },
            )

        verification_db = test_session()
        try:
            rows = (
                verification_db.query(Message)
                .filter(Message.conversation_id == session_id)
                .order_by(Message.created_at.asc())
                .all()
            )
            self.assertEqual(2, len(rows))
            self.assertEqual("failed_turn", rows[0].message_type)
            self.assertEqual("internal_error", rows[1].message_type)
        finally:
            verification_db.close()
