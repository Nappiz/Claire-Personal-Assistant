"""Conversation pin persistence and ordering regression coverage."""

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base
from models.conversation import Conversation
from routes.chat_routes import get_sessions, set_session_pin
from schemas.chat_sch import ConversationPinUpdate


class SessionPinTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_pinned_session_is_persisted_and_sorted_first(self):
        now = datetime.now(timezone.utc)
        older = Conversation(title="Lama", updated_at=now - timedelta(days=1))
        newer = Conversation(title="Baru", updated_at=now)
        self.db.add_all([older, newer])
        self.db.commit()

        result = set_session_pin(
            older.id,
            ConversationPinUpdate(is_pinned=True),
            self.db,
        )

        self.assertTrue(result["is_pinned"])
        sessions = get_sessions(self.db)
        self.assertEqual(older.id, sessions[0]["id"])
        self.assertTrue(sessions[0]["is_pinned"])

        unpinned = set_session_pin(
            older.id,
            ConversationPinUpdate(is_pinned=False),
            self.db,
        )
        self.assertFalse(unpinned["is_pinned"])
        self.assertIsNone(unpinned["pinned_at"])

