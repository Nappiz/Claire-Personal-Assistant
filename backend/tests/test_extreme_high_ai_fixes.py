"""Regression coverage for HIGH findings in the 2026-09-12 extreme AI audit."""

import inspect
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.message import Message
from schemas.chat_sch import MemoryContext, RetrievedMemory, WebPageContent, WebSearchContext
from services import llm_service, memory_service
from services.neo4j_service import Neo4jService


class _GraphResult:
    def __init__(self, record=None, rows=None):
        self.record = record
        self.rows = rows or []

    def single(self):
        return self.record

    def __iter__(self):
        return iter(self.rows)


class _GraphTransaction:
    def __init__(self, retraction_rows=None):
        self.calls = []
        self.retraction_rows = retraction_rows or []

    def run(self, query, **params):
        self.calls.append((query, params))
        if "RETURN collect(old.fact_id) AS fact_ids" in query:
            return _GraphResult({"fact_ids": [], "newest_event_at": 0})
        if "RETURN r.fact_id AS fact_id" in query:
            return _GraphResult({"fact_id": "fact-new"})
        if "old.retracted_at" in query:
            return _GraphResult(rows=self.retraction_rows)
        return _GraphResult()


class _GraphSession:
    def __init__(self, tx):
        self.tx = tx
        self.write_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute_write(self, callback):
        self.write_calls += 1
        return callback(self.tx)


class _GraphDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


class ExtremeHighAIFixTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _conversation(self, *, message_count=0, summary_pending=False):
        db = self.SessionLocal()
        try:
            row = Conversation(
                title="Test",
                message_count=message_count,
                summary_pending=summary_pending,
            )
            db.add(row)
            db.commit()
            return str(row.id)
        finally:
            db.close()

    def _job(self, *, event_at=None):
        conversation_id = self._conversation(message_count=1)
        db = self.SessionLocal()
        try:
            message = Message(
                conversation_id=conversation_id,
                role="user",
                content="Aku sekarang bekerja di Beta",
                message_type="normal",
                turn_sequence=1,
            )
            db.add(message)
            db.flush()
            job = MemoryOutbox(
                conversation_id=conversation_id,
                user_message_id=message.id,
                user_message=message.content,
                assistant_response="Oke",
                event_at=event_at or datetime.now(timezone.utc),
            )
            db.add(job)
            db.commit()
            return conversation_id, str(message.id), str(job.id)
        finally:
            db.close()

    def test_h01_scheduled_sync_memory_work_is_offloaded(self):
        import main

        self.assertIn("asyncio.to_thread", inspect.getsource(main.memory_maintenance_task))
        self.assertIn("asyncio.to_thread", inspect.getsource(main.memory_outbox_retry_task))

    def test_h02_router_and_scope_share_the_total_deadline(self):
        def slow(*_args, **_kwargs):
            time.sleep(0.25)
            return llm_service.MemoryRouteDecision("not_needed", [])

        started = time.monotonic()
        with patch.object(memory_service.settings, "MEMORY_RETRIEVAL_TIMEOUT_SECONDS", 0.05), patch.object(
            memory_service, "route_memory_query", side_effect=slow
        ), patch.object(memory_service, "_resolve_project_scope", side_effect=slow):
            context = memory_service.retrieve_context("ingat pekerjaanku")
        self.assertLess(time.monotonic() - started, 0.18)
        self.assertTrue(context.retrieval_status.degraded)
        self.assertIn("memory_router_timeout", context.retrieval_status.warnings)

    def test_h04_claim_has_owner_token_and_cannot_be_stolen_before_expiry(self):
        _, _, job_id = self._job()
        with patch("configs.database.SessionLocal", self.SessionLocal):
            first = memory_service._claim_memory_job(job_id)
            second = memory_service._claim_memory_job(job_id)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            db = self.SessionLocal()
            db.get(MemoryOutbox, job_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
            db.close()
            third = memory_service._claim_memory_job(job_id)
        self.assertNotEqual(first, third)

        _, _, legacy_job_id = self._job()
        db = self.SessionLocal()
        legacy = db.get(MemoryOutbox, legacy_job_id)
        legacy.status = "processing"
        legacy.lease_token = None
        legacy.lease_expires_at = None
        legacy.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
        with patch("configs.database.SessionLocal", self.SessionLocal):
            self.assertIsNone(memory_service._claim_memory_job(legacy_job_id))

    def test_h05_write_crossing_tombstone_triggers_compensation(self):
        conversation_id, _, job_id = self._job()

        def delete_during_write(*_args, **_kwargs):
            db = self.SessionLocal()
            conversation = db.get(Conversation, conversation_id)
            conversation.deleted_at = datetime.now(timezone.utc)
            memory_service.cancel_memory_jobs_for_conversation(conversation_id, db)
            db.commit()
            db.close()

        with patch("configs.database.SessionLocal", self.SessionLocal), patch.object(
            memory_service, "extract_knowledge", return_value={
                "nodes": [
                    {"id": "p", "name": "nafiz"},
                    {"id": "o", "name": "beta"},
                ],
                "edges": [{"source": "p", "target": "o", "relation": "WORKS_AT"}],
            }
        ), patch.object(memory_service, "save_memory", side_effect=delete_during_write), patch.object(
            memory_service, "_compensate_deleted_conversation"
        ) as compensate:
            memory_service.process_memory_job(job_id)
        compensate.assert_called_once()

    def test_h06_graph_batch_uses_one_write_transaction(self):
        tx = _GraphTransaction()
        session = _GraphSession(tx)
        service = object.__new__(Neo4jService)
        service.driver = _GraphDriver(session)
        service.merge_knowledge(
            [
                {"id": "p", "label": "Person", "name": "nafiz"},
                {"id": "o", "label": "Organization", "name": "beta"},
            ],
            [{"source": "p", "target": "o", "relation": "WORKS_AT"}],
            event_id="event-1",
        )
        self.assertEqual(1, session.write_calls)
        self.assertTrue(any("memory_write_fence" in query for query, _ in tx.calls))

    def test_h07_retry_uses_original_event_time(self):
        event_at = datetime(2020, 1, 2, tzinfo=timezone.utc)
        _, _, job_id = self._job(event_at=event_at)
        extraction_times = []
        graph_times = []

        def extract(*_args, **kwargs):
            extraction_times.append(kwargs["event_at"])
            return {"nodes": [{"id": "p", "label": "Person", "name": "nafiz"}], "edges": []}

        def merge(*_args, **kwargs):
            graph_times.append(kwargs["event_at"])
            return {}

        with patch("configs.database.SessionLocal", self.SessionLocal), patch.object(
            memory_service, "extract_knowledge", side_effect=extract
        ), patch.object(memory_service, "save_memory"), patch.object(
            memory_service.neo4j_client, "merge_knowledge", side_effect=merge
        ):
            memory_service.process_memory_job(job_id)
        self.assertEqual(event_at, extraction_times[0].replace(tzinfo=timezone.utc))
        self.assertEqual(event_at, graph_times[0].replace(tzinfo=timezone.utc))

    def test_h08_explicit_retraction_is_applied_without_replacement_edge(self):
        tx = _GraphTransaction(retraction_rows=[{"source_message_ids": ["old-message"]}])
        service = object.__new__(Neo4jService)
        service.driver = _GraphDriver(_GraphSession(tx))
        result = service.merge_knowledge(
            [{"id": "p", "label": "Person", "name": "nafiz"}],
            [],
            retractions=[{"source": "p", "relation": "WORKS_AT", "fact_id": "old-fact"}],
            source_message_id="new-message",
        )
        self.assertEqual(["old-message"], result["invalidated_source_message_ids"])
        self.assertTrue(any("old.retracted_at" in query for query, _ in tx.calls))

    def test_h09_graph_invalidation_disables_sqlite_vector_source(self):
        _, message_id, job_id = self._job()
        extracted = {
            "nodes": [{"id": "p", "label": "Person", "name": "nafiz"}],
            "edges": [],
        }
        with patch("configs.database.SessionLocal", self.SessionLocal), patch.object(
            memory_service, "extract_knowledge", return_value=extracted
        ), patch.object(memory_service, "save_memory"), patch.object(
            memory_service.neo4j_client,
            "merge_knowledge",
            return_value={"invalidated_source_message_ids": [message_id]},
        ), patch("services.qdrant_service.set_memories_status") as vector_status:
            memory_service.process_memory_job(job_id)
        db = self.SessionLocal()
        try:
            self.assertEqual("inactive", db.get(Message, message_id).memory_status)
        finally:
            db.close()
        vector_status.assert_called_once()

    def test_h10_summary_compare_and_swap_rejects_stale_writer(self):
        conversation_id = self._conversation(message_count=40, summary_pending=True)
        db = self.SessionLocal()
        for sequence in range(1, 21):
            db.add(Message(conversation_id=conversation_id, role="user", content=f"u{sequence}", message_type="normal", turn_sequence=sequence))
            db.add(Message(conversation_id=conversation_id, role="assistant", content=f"a{sequence}", message_type="normal", turn_sequence=sequence))
        conversation = db.get(Conversation, conversation_id)
        conversation.next_turn_sequence = 21
        db.commit()
        db.close()

        def concurrent_turn(_summary, _messages):
            memory_service.begin_turn(conversation_id, "concurrent", str(uuid.uuid4()))
            return "stale summary"

        with patch("configs.database.SessionLocal", self.SessionLocal), patch.object(
            llm_service, "generate_session_summary", side_effect=concurrent_turn
        ):
            result = memory_service.process_conversation_summary(conversation_id)
        self.assertEqual("stale", result["status"])
        db = self.SessionLocal()
        try:
            self.assertIsNone(db.get(Conversation, conversation_id).summary)
        finally:
            db.close()

    def test_h11_turn_identity_is_retryable_and_idempotent(self):
        conversation_id = self._conversation()
        turn_id = str(uuid.uuid4())
        with patch("configs.database.SessionLocal", self.SessionLocal):
            first = memory_service.begin_turn(conversation_id, "halo", turn_id)
            with self.assertRaises(memory_service.TurnConflictError):
                memory_service.begin_turn(conversation_id, "lain", str(uuid.uuid4()))
            memory_service.mark_turn_status(conversation_id, turn_id, "interrupted_turn")
            retry = memory_service.begin_turn(conversation_id, "halo", turn_id)
            self.assertEqual(first["user_message_id"], retry["user_message_id"])
            memory_service.save_interaction(
                conversation_id,
                "halo",
                "hai",
                {},
                turn_id=turn_id,
                turn_sequence=retry["turn_sequence"],
                user_message_id=retry["user_message_id"],
                process_memory=False,
            )
            cached = memory_service.begin_turn(conversation_id, "halo", turn_id)
        self.assertTrue(cached["completed"])
        self.assertEqual("hai", cached["cached_reply"])

    def test_h12_prompt_is_bounded_by_tokens_instead_of_message_count(self):
        context = MemoryContext(
            qdrant_context=[
                RetrievedMemory(content="v" * 20_000, score=0.9) for _ in range(10)
            ],
            neo4j_context=["g" * 10_000 for _ in range(50)],
            web_context=WebSearchContext(
                status="ok",
                pages=[
                    WebPageContent(url=f"https://example.com/{index}", content="w" * 100_000)
                    for index in range(8)
                ],
            ),
        )
        messages = llm_service._build_chat_messages(
            "u" * 24_000,
            context,
            session_history=[{"role": "user", "content": "h" * 20_000} for _ in range(200)],
            session_summary="s" * 50_000,
        )
        total = sum(llm_service._estimate_prompt_tokens(item["content"]) + 8 for item in messages)
        self.assertLessEqual(total, llm_service.settings.CHAT_INPUT_TOKEN_BUDGET)
