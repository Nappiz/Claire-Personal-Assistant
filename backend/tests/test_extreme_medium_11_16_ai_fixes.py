"""Regression tests for M11-M16 using real temporary SQLite/Qdrant stores."""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base
from models.conversation import Conversation
from models.message import Message
from models.memory_outbox import MemoryOutbox
from schemas.chat_sch import MemoryContext, WebPageContent, WebSearchContext, WebSearchResult
from services import llm_service, memory_service, qdrant_service, web_reader_service, web_search_service
from test_llm_web_tool_loop import _FakeLLMClient, _planning_response, _tool_call


def metadata(text, **extra):
    return {
        "session_id": "session", "message_id": "message", "source_role": "user",
        "epistemic_status": "user_assertion", "stored_at": "2026-09-13T00:00:00",
        "assertion_spans": [{"text": text, "modality": "asserted_fact", "polarity": "positive"}],
        **extra,
    }


class VectorReconciliationTests(TestCase):
    def setUp(self):
        self.client = QdrantClient(location=":memory:")
        self.client.create_collection(qdrant_service.COLLECTION_NAME,
            vectors_config=VectorParams(size=2, distance=Distance.COSINE))
        self.addCleanup(self.client.close)
        self.addCleanup(patch.stopall)
        patch.object(qdrant_service, "client", self.client).start()
        patch.object(qdrant_service, "_memory_chunk_offsets", side_effect=lambda text: [(0, len(text))]).start()
        self.embed = patch.object(qdrant_service, "embed_text", return_value=[1.0, 0.0]).start()

    def test_m11_same_count_does_not_hide_missing_event_and_restart_skips_embedding(self):
        a, b, orphan = [str(uuid.uuid4()) for _ in range(3)]
        qdrant_service.save_memory("fact A", metadata("fact A"), point_id=a)
        qdrant_service.save_memory("fact X", metadata("fact X"), point_id=orphan)
        self.assertEqual(2, self.client.count(qdrant_service.COLLECTION_NAME).count)
        self.embed.reset_mock()
        self.assertFalse(qdrant_service.reconcile_memory("fact A", metadata("fact A"), point_id=a))
        self.assertTrue(qdrant_service.reconcile_memory("fact B", metadata("fact B"), point_id=b))
        self.embed.assert_called_once()
        self.assertEqual(1, len(self.client.retrieve(qdrant_service.COLLECTION_NAME, [b])))
        self.embed.reset_mock()
        self.assertFalse(qdrant_service.reconcile_memory("fact B", metadata("fact B"), point_id=b))
        self.embed.assert_not_called()

    def test_m11_repairs_content_and_scope_with_unchanged_event_id(self):
        event_id = str(uuid.uuid4())
        qdrant_service.save_memory("old fact", metadata("old fact"), point_id=event_id)
        self.assertTrue(qdrant_service.reconcile_memory("new fact", metadata("new fact", project_id="atlas"), point_id=event_id))
        payload = self.client.retrieve(qdrant_service.COLLECTION_NAME, [event_id])[0].payload
        self.assertEqual(("new fact", "atlas", "project"), (payload["text"], payload["project_id"], payload["scope"]))

    def test_m11_same_dimension_model_or_revision_change_requires_reembedding(self):
        event_id = str(uuid.uuid4())
        qdrant_service.save_memory("fact", metadata("fact"), point_id=event_id)
        original = qdrant_service.embedding_signature()
        with patch.object(qdrant_service.settings, "EMBEDDING_MODEL_NAME", "other-semantic-model"):
            self.assertNotEqual(original, qdrant_service.embedding_signature())
            self.assertEqual([], qdrant_service.search_memory("fact"))
            self.assertTrue(qdrant_service.reconcile_memory("fact", metadata("fact"), point_id=event_id))
            with patch.object(qdrant_service.settings, "EMBEDDING_MODEL_REVISION", "pinned-new-weights"):
                self.assertTrue(qdrant_service.reconcile_memory("fact", metadata("fact"), point_id=event_id))

    def test_m11_missing_chunk_is_repaired_and_obsolete_chunks_are_removed(self):
        event_id = str(uuid.uuid4())
        text = "abcdefgh"
        with patch.object(qdrant_service, "_memory_chunk_offsets", return_value=[(0, 4), (4, 8)]), patch.object(
            qdrant_service, "embed_texts", return_value=[[1.0, 0.0], [1.0, 0.0]]
        ):
            qdrant_service.save_memory(text, metadata(text), point_id=event_id)
            tail_id = qdrant_service._chunk_point_id(event_id, 1)
            self.client.delete(qdrant_service.COLLECTION_NAME, [tail_id])
            self.assertTrue(qdrant_service.reconcile_memory(text, metadata(text), point_id=event_id))
            self.assertEqual(2, self.client.count(qdrant_service.COLLECTION_NAME).count)
        self.assertTrue(qdrant_service.reconcile_memory(text, metadata(text), point_id=event_id))
        self.assertEqual(1, self.client.count(qdrant_service.COLLECTION_NAME).count)

    def test_m11_resume_prunes_leftover_chunk_without_reembedding_current_projection(self):
        event_id = str(uuid.uuid4())
        qdrant_service.save_memory("fact", metadata("fact"), point_id=event_id)
        first = self.client.retrieve(qdrant_service.COLLECTION_NAME, [event_id], with_vectors=True)[0]
        from qdrant_client.http.models import PointStruct
        self.client.upsert(qdrant_service.COLLECTION_NAME, [PointStruct(
            id=qdrant_service._chunk_point_id(event_id, 1), vector=first.vector,
            payload={**first.payload, "text": "obsolete tail"},
        )])
        self.embed.reset_mock()
        self.assertFalse(qdrant_service.reconcile_memory("fact", metadata("fact"), point_id=event_id))
        self.embed.assert_not_called()
        self.assertEqual(1, self.client.count(qdrant_service.COLLECTION_NAME).count)


class DurableHistoryAndReindexTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        self.conversation = str(uuid.uuid4())
        with self.sessions() as db:
            db.add(Conversation(id=self.conversation, next_turn_sequence=17))
            db.commit()

    def add_job(self, db, index, **extra):
        message_id = str(uuid.uuid4())
        db.add(Message(id=message_id, conversation_id=self.conversation, role="user", content="fact"))
        db.add(MemoryOutbox(id=str(uuid.UUID(int=index + 1)), conversation_id=self.conversation,
            user_message_id=message_id, user_message="fact", assistant_response="ok",
            extraction_completed=True, extracted_knowledge={"nodes": [], "edges": []}, **extra))
        return message_id

    def test_m11_keyset_scan_covers_more_than_two_batches_and_skips_unextracted_jobs(self):
        with self.sessions() as db:
            for index in range(205):
                self.add_job(db, index)
            unready = MemoryOutbox(id=str(uuid.UUID(int=1000)), conversation_id=self.conversation,
                user_message_id=str(uuid.uuid4()), user_message="pending", assistant_response="ok")
            db.add(Message(id=unready.user_message_id, conversation_id=self.conversation, role="user", content="pending"))
            db.add(unready)
            db.commit()
        with patch("configs.database.SessionLocal", self.sessions):
            rows = list(memory_service._vector_reindex_snapshots(batch_size=100))
        self.assertEqual(205, len(rows))
        self.assertEqual(205, len({row["id"] for row in rows}))

    def test_m11_deletion_during_reconciliation_marks_late_write_inactive(self):
        with self.sessions() as db:
            message_id = self.add_job(db, 1)
            job = db.get(MemoryOutbox, str(uuid.UUID(int=2)))
            job.extracted_knowledge = {"nodes": [{"id": "a", "name": "nafiz"}, {"id": "b", "name": "acme"}],
                                      "edges": [{"source": "a", "target": "b", "relation": "WORKS_AT"}]}
            db.commit()
        def delete_during_write(*_args, **_kwargs):
            with self.sessions() as db:
                db.get(Conversation, self.conversation).deleted_at = datetime.now(timezone.utc)
                db.commit()
            return True
        with patch("configs.database.SessionLocal", self.sessions), patch.object(
            memory_service, "reconcile_memory", side_effect=delete_during_write
        ), patch.object(qdrant_service, "set_memories_status") as mark:
            result = memory_service.reindex_vector_memory_from_outbox()
        mark.assert_called_once_with([message_id], "inactive")
        self.assertEqual(0, result["indexed"])

    def test_m11_full_outbox_reconciliation_resumes_from_durable_projection(self):
        with self.sessions() as db:
            self.add_job(db, 1)
            db.flush()
            db.get(MemoryOutbox, str(uuid.UUID(int=2))).extracted_knowledge = {
                "nodes": [{"id": "a", "name": "nafiz"}, {"id": "b", "name": "acme"}],
                "edges": [{"source": "a", "target": "b", "relation": "WORKS_AT"}],
            }
            db.commit()
        client = QdrantClient(location=":memory:")
        try:
            client.create_collection(qdrant_service.COLLECTION_NAME,
                vectors_config=VectorParams(size=2, distance=Distance.COSINE))
            with patch("configs.database.SessionLocal", self.sessions), patch.object(
                qdrant_service, "client", client
            ), patch.object(qdrant_service, "_memory_chunk_offsets", side_effect=lambda text: [(0, len(text))]), patch.object(
                qdrant_service, "embed_text", return_value=[1.0, 0.0]
            ) as embed:
                first = memory_service.reindex_vector_memory_from_outbox()
                second = memory_service.reindex_vector_memory_from_outbox()
            self.assertEqual((1, 0), (first["indexed"], first["failed"]))
            self.assertEqual((0, 1), (second["indexed"], second["skipped"]))
            embed.assert_called_once()
        finally:
            client.close()

    def test_m16_equal_or_skewed_timestamps_preserve_turn_role_order_everywhere(self):
        from routes.chat_routes import get_history
        same_time = datetime(2026, 9, 13)
        with self.sessions() as db:
            for sequence in (1, 2, 3):
                for role in ("assistant", "user"):
                    db.add(Message(conversation_id=self.conversation, turn_sequence=sequence,
                        role=role, content=f"{sequence}:{role}", created_at=same_time))
            db.commit()
            self.assertEqual(["user", "assistant"] * 3,
                [row["role"] for row in memory_service.get_session_history(db, self.conversation)])
            self.assertEqual(["user", "assistant"] * 3,
                [row["role"] for row in get_history(self.conversation, db)])
            user = db.query(Message).filter_by(turn_sequence=1, role="user").one()
            user.created_at = datetime(2026, 9, 14)
            db.commit()
            self.assertEqual("1:user", memory_service.get_session_history(db, self.conversation)[0]["content"])

    def test_m16_summary_uses_same_role_order_for_tied_timestamps(self):
        with self.sessions() as db:
            for sequence in range(1, 17):
                for role in ("assistant", "user"):
                    db.add(Message(conversation_id=self.conversation, turn_sequence=sequence,
                        role=role, content=f"{sequence}:{role}", created_at=datetime(2026, 9, 13)))
            db.commit()
        with patch("configs.database.SessionLocal", self.sessions), patch.object(
            llm_service, "generate_session_summary", return_value="summary"
        ) as summary:
            result = memory_service.process_conversation_summary(self.conversation)
        self.assertEqual("updated", result["status"])
        self.assertEqual(["user", "assistant"], [message["role"] for message in summary.call_args.args[1]])

    def test_m16_legacy_backfill_preserves_insertion_pairs_instead_of_uuid_order(self):
        import main
        ids = ["f" * 36, "a" * 36, "e" * 36, "b" * 36]
        with self.sessions() as db:
            for message_id, role in zip(ids, ["user", "assistant", "user", "assistant"]):
                db.add(Message(id=message_id, conversation_id=self.conversation, role=role,
                    content=role, created_at=datetime(2026, 9, 13)))
                db.flush()
            db.commit()
        with patch.object(main, "engine", self.engine):
            main.ensure_local_legacy_schema()
        with self.sessions() as db:
            self.assertEqual([1, 1, 2, 2], [db.get(Message, message_id).turn_sequence for message_id in ids])

    def test_m16_legacy_unanswered_user_does_not_share_turn_with_next_user(self):
        import main
        ids = [str(uuid.uuid4()) for _ in range(3)]
        with self.sessions() as db:
            for message_id, role in zip(ids, ["user", "user", "assistant"]):
                db.add(Message(id=message_id, conversation_id=self.conversation, role=role,
                    content=role, created_at=datetime(2026, 9, 13)))
                db.flush()
            db.commit()
        with patch.object(main, "engine", self.engine):
            main.ensure_local_legacy_schema()
        with self.sessions() as db:
            self.assertEqual([1, 2, 2], [db.get(Message, message_id).turn_sequence for message_id in ids])


class SearchClient:
    def __init__(self, responses):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _url, *, params):
        payload = self.responses[params["q"]]
        if isinstance(payload, BaseException):
            raise payload
        return NS(raise_for_status=lambda: None, json=lambda: payload)


def search_payload(title, url):
    return {"results": [{"title": title, "url": url, "content": title, "engine": "google"}]}


class WebResilienceTests(IsolatedAsyncioTestCase):
    async def test_m13_partial_search_preserves_success_in_strict_mode(self):
        client = SearchClient({"good": search_payload("Database latency", "https://example.com/good"),
                               "bad": httpx.ReadTimeout("timed out")})
        with patch.object(web_search_service.httpx, "AsyncClient", return_value=client), patch.object(
            web_search_service.settings, "WEB_SEARCH_ENABLED", True
        ):
            context = await web_search_service.retrieve_web_context("goal", plan=web_search_service.WebSearchPlan(
                True, query="good", queries=("good", "bad")), raise_on_error=True)
        self.assertEqual("ok", context.status)
        self.assertEqual(1, len(context.results))
        self.assertIn("web_search_partial_failure", context.warnings)

    async def test_m14_zero_overlap_translation_and_per_query_representative_survive(self):
        english = "https://example.com/english"
        client = SearchClient({"reduce latency": search_payload("How to reduce database latency", english),
            "mempercepat": search_payload("Cara mempercepat basis data", "https://example.com/indonesian")})
        with patch.object(web_search_service.httpx, "AsyncClient", return_value=client), patch.object(
            web_search_service.settings, "WEB_SEARCH_ENABLED", True
        ), patch.object(web_search_service.settings, "WEB_SEARCH_MAX_RESULTS", 2):
            context = await web_search_service.retrieve_web_context("cara mempercepat basis data",
                plan=web_search_service.WebSearchPlan(True, query="reduce latency",
                    queries=("reduce latency", "mempercepat"), research_goal="cara mempercepat basis data"))
        self.assertEqual({english, "https://example.com/indonesian"}, {result.url for result in context.results})

    async def run_llm(self, client, context, user="Read source", **patches):
        with patch.object(llm_service, "_get_llm_connection", return_value=("key", "url")), patch.object(
            llm_service, "_create_async_llm_client", return_value=client
        ):
            return [event async for event in llm_service.generate_chat_response_stream(user, context)]

    def context(self):
        return MemoryContext(web_context=WebSearchContext(status="ok", results=[
            WebSearchResult(title="Good", url="https://example.com/good", engine="google"),
            WebSearchResult(title="Bad", url="https://example.com/bad", engine="google"),
        ]))

    async def test_m12_duplicate_pending_urls_fetch_once_and_reply_to_every_call_id(self):
        calls = [_tool_call(f"read-{index}", "read_url", {"url": "https://example.com/good"}, "signature") for index in range(2)]
        client = _FakeLLMClient([_planning_response(*calls)])
        reader = AsyncMock(return_value=WebPageContent(url="https://example.com/good", content="Evidence"))
        with patch.object(web_reader_service, "read_url", reader):
            await self.run_llm(client, self.context())
        reader.assert_awaited_once()
        payloads = [json.loads(message["content"]) for message in client.calls[-1]["messages"] if message["role"] == "tool"]
        self.assertEqual(2, len(payloads))
        self.assertTrue(all(payload["ok"] for payload in payloads))

    async def test_m13_failed_page_keeps_other_page_and_error_result(self):
        calls = [_tool_call(url, "read_url", {"url": f"https://example.com/{url}"}, "signature") for url in ("good", "bad")]
        client = _FakeLLMClient([_planning_response(*calls)])
        async def read(url, **_kwargs):
            if url.endswith("bad"):
                raise httpx.ReadTimeout("unavailable")
            return WebPageContent(url=url, content="Useful evidence")
        context = self.context()
        with patch.object(web_reader_service, "read_url", new=read):
            events = await self.run_llm(client, context)
        self.assertEqual(1, len(context.web_context.pages))
        payloads = [json.loads(message["content"]) for message in client.calls[-1]["messages"] if message["role"] == "tool"]
        self.assertEqual([True, False], [payload["ok"] for payload in payloads])
        self.assertTrue(any(event["type"] == "delta" for event in events))

    async def test_m13_invalid_read_arguments_can_be_corrected_next_round(self):
        bad = _tool_call("bad", "read_url", {}, "signature")
        good = _tool_call("good", "read_url", {"url": "https://example.com/good"}, "signature")
        client = _FakeLLMClient([_planning_response(bad), _planning_response(good)])
        with patch.object(web_reader_service, "read_url", new=AsyncMock(
            return_value=WebPageContent(url="https://example.com/good", content="Evidence")
        )):
            events = await self.run_llm(client, self.context())
        self.assertTrue(any(event["type"] == "delta" for event in events))
        messages = client.calls[-1]["messages"]
        self.assertEqual(2, sum(message["role"] == "tool" for message in messages))

    async def test_m13_failed_url_can_be_replaced_with_remaining_read_budget(self):
        bad = _tool_call("bad", "read_url", {"url": "https://example.com/bad"}, "signature")
        good = _tool_call("good", "read_url", {"url": "https://example.com/good"}, "signature")
        client = _FakeLLMClient([_planning_response(bad), _planning_response(good)])
        reader = AsyncMock(side_effect=[httpx.ReadTimeout("timeout"),
            WebPageContent(url="https://example.com/good", content="Replacement evidence")])
        context = self.context()
        with patch.object(web_reader_service, "read_url", reader):
            events = await self.run_llm(client, context)
        self.assertEqual(2, reader.await_count)
        self.assertEqual("Replacement evidence", context.web_context.pages[0].content)
        self.assertTrue(any(event["type"] == "delta" for event in events))

    async def test_m13_all_search_failures_are_tool_error_and_model_can_explain_limit(self):
        search = _tool_call("search", "web_search", {"queries": ["fresh fact"]}, "signature")
        answer = NS(choices=[NS(message=NS(content="Sumber sedang tidak tersedia.", tool_calls=[]))], usage=None)
        client = _FakeLLMClient([_planning_response(search), answer])
        context = MemoryContext()
        with patch.object(web_search_service, "retrieve_web_context", new=AsyncMock(side_effect=httpx.ConnectError("offline"))):
            events = await self.run_llm(client, context, user="Cari fakta terbaru")
        self.assertEqual("unavailable", context.web_context.status)
        self.assertIn("tidak tersedia", "".join(
            event["delta"] for event in events if event["type"] == "delta"))

    async def test_m15_greeting_streams_with_one_generation(self):
        client = _FakeLLMClient([])
        events = await self.run_llm(client, MemoryContext(), user="Halo Claire!")
        self.assertEqual(1, len(client.calls))
        self.assertTrue(client.calls[0]["stream"])
        self.assertTrue(any(event["type"] == "delta" for event in events))

    async def test_m15_non_tool_planner_answer_is_reused_verbatim_with_usage(self):
        answer = _planning_response()
        answer.choices[0].message.content = "  Jawaban langsung\nbaris kedua  "
        client = _FakeLLMClient([answer])
        events = await self.run_llm(client, MemoryContext(), user="Jelaskan konsep recursion")
        self.assertEqual(1, len(client.calls))
        deltas = [event["delta"] for event in events if event["type"] == "delta"]
        self.assertGreater(len(deltas), 1)
        self.assertTrue(client.calls[0]["stream"])
        self.assertEqual(answer.choices[0].message.content, "".join(deltas))
        self.assertEqual(12, next(event["usage"]["total_tokens"] for event in events if event["type"] == "usage"))

    async def test_m15_greeting_with_fresh_fact_does_not_bypass_web_decision(self):
        answer = _planning_response()
        answer.choices[0].message.content = "Answer"
        client = _FakeLLMClient([answer])
        await self.run_llm(client, MemoryContext(), user="Halo Claire, berapa harga emas hari ini?")
        self.assertIn("tools", client.calls[0])
