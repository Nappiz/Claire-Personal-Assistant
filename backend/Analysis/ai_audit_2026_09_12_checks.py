"""Read-only AI audit probes: synthetic SQLite, mocked network, no live stores.

Run from backend: venv/Scripts/python.exe Analysis/ai_audit_2026_09_12_checks.py
Use --existing to run the existing AI regression suite in the same isolation.
Assertions document CURRENT defects, not the desired fixed behavior.
"""
import asyncio
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="claire_ai_audit_")
os.environ.update({
    "DATABASE_URL": "sqlite:///" + (Path(TEMP.name) / "audit.sqlite").as_posix(),
    "QDRANT_PATH": str(Path(TEMP.name) / "qdrant"),
    "NEO4J_URI": "bolt://127.0.0.1:1", "NEO4J_USER": "audit", "NEO4J_PASSWORD": "audit",
    "GEMINI_API_KEY": "audit-placeholder", "GROQ_API_KEY": "audit-placeholder",
    "HF_TOKEN": "", "JINA_API_KEY": "", "HF_HUB_OFFLINE": "1",
})
# Block outbound name resolution; Windows asyncio still needs its socketpair.
network_guard = patch.object(socket, "getaddrinfo", side_effect=AssertionError("AUDIT: network forbidden"))
network_guard.start()
import neo4j
graph_guard = patch.object(neo4j.GraphDatabase, "driver", return_value=MagicMock())
graph_guard.start()
from configs.database import Base, SessionLocal, engine
import models
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.message import Message
from schemas.chat_sch import MemoryContext, ProjectScopeContext, WebSearchContext, WebSearchResult
from services import llm_service as llm, memory_service as mem, qdrant_service as vec, web_search_service as web
from services.neo4j_service import Neo4jService
Base.metadata.create_all(engine)
logging.disable(logging.CRITICAL)


def create_job(status="pending", text="Aku suka kopi"):
    with SessionLocal() as db:
        c = Conversation(title="audit")
        db.add(c)
        db.flush()
        j = MemoryOutbox(conversation_id=c.id, user_message=text,
                         assistant_response="Baik", status=status)
        db.add(j)
        db.commit()
        return c.id, j.id


def call(name, args, ident="call-1"):
    return NS(id=ident, function=NS(name=name, arguments=json.dumps(args)))


def plan(*calls):
    return NS(choices=[NS(message=NS(content=None, tool_calls=list(calls)))], usage=None)


class FakeStream:
    def __init__(self, parts):
        self.parts = iter(parts)
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
    def __aiter__(self): return self
    async def __anext__(self):
        try: part = next(self.parts)
        except StopIteration: raise StopAsyncIteration
        return NS(choices=[NS(delta=NS(content=part), finish_reason=None)], usage=None)


class Client:
    def __init__(self, plans=(), parts=("answer",)):
        self.plans = iter(plans)
        self.parts = parts
        self.calls = []
        self.chat = NS(completions=self)
    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"): return FakeStream(self.parts)
        return next(self.plans)
    async def close(self): pass


class AuditChecks(unittest.TestCase):
    def test_same_timestamp_messages_reverse_role_order(self):
        cid, _ = create_job()
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with SessionLocal() as db:
            db.add(Message(conversation_id=cid, role="user", content="question", created_at=stamp))
            db.add(Message(conversation_id=cid, role="assistant", content="answer", created_at=stamp))
            db.commit()
            history = mem.get_session_history(db, cid)
        self.assertEqual([item["role"] for item in history], ["assistant", "user"])

    def test_identity_paraphrases_split_the_same_person(self):
        first = Neo4jService._entity_key("Person", "siska", "ibu nafiz")
        second = Neo4jService._entity_key("Person", "siska", "ibu dari nafiz")
        self.assertNotEqual(first, second)

    def test_all_project_nodes_collapse_to_active_project(self):
        class Result:
            def single(self): return {"fact_id": "test-fact", "fact_ids": []}
        class Session:
            def __init__(self): self.calls = []
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def run(self, query, **kwargs):
                self.calls.append((query, kwargs))
                return Result()
        session = Session()
        service = object.__new__(Neo4jService)
        service.driver = NS(session=lambda: session)
        service.merge_knowledge(
            [{"id": "a", "label": "Project", "name": "atlas"}, {"id": "b", "label": "Project", "name": "boreal"}],
            [{"source": "a", "target": "b", "relation": "DEPENDS_ON"}],
            project_id="p-atlas", project_name="Atlas",
        )
        merge = next(params for query, params in session.calls if "MERGE (a)-[r:DEPENDS_ON" in query)
        self.assertEqual(merge["source"], merge["target"])
        node_names = [params["name"] for query, params in session.calls if "MERGE (n:Entity" in query]
        self.assertEqual(node_names, ["atlas", "boreal"])

    def test_old_outbox_timestamp_not_used_for_extraction(self):
        _, jid = create_job(text="Besok aku menghadiri konferensi")
        with SessionLocal() as db:
            db.get(MemoryOutbox, jid).created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.commit()
        response = NS(choices=[NS(message=NS(content='{"nodes": [], "edges": []}'))])
        with patch.object(llm, "_current_temporal_context", return_value={"date_iso": "2026-09-12"}), patch.object(llm, "_memory_completion", return_value=response) as complete, patch.object(mem, "save_memory"):
            mem.process_memory_job(jid)
        prompt = complete.call_args.kwargs["messages"][0]["content"]
        self.assertIn("2026-09-12", prompt)
        self.assertNotIn("2020-01-01", prompt)

    def test_current_read_does_not_reconcile_vector_with_graph(self):
        stale = {"content": "Aku kerja di Acme", "score": 0.99, "source_role": "user", "epistemic_status": "user_assertion"}
        with patch.object(mem, "route_memory_query", return_value=llm.MemoryRouteDecision("needed", ["nafiz"])), patch.object(mem, "search_memory", return_value=[stale]), patch.object(mem.neo4j_client, "search_knowledge", return_value=["[current: true] nafiz --[WORKS_AT]--> beta"]):
            context = mem.retrieve_context("Aku kerja di mana?")
        self.assertIn("Acme", context.qdrant_context[0].content)
        prompt = llm._build_chat_messages("Aku kerja di mana?", context)[0]["content"]
        self.assertIn("Acme", prompt)
        self.assertIn("beta", prompt)

    def test_processing_job_can_be_claimed_again(self):
        _, jid = create_job("processing")
        with patch.object(mem, "extract_knowledge", return_value={"nodes": [], "edges": []}) as extract, patch.object(mem, "save_memory"):
            result = mem.process_memory_job(jid)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(extract.call_count, 1)

    def test_vector_write_can_finish_after_session_deletion(self):
        cid, jid = create_job()
        vectors = {}
        def paused_upsert(text, metadata, point_id):
            # Worker passed _memory_job_is_active, then deletion wins the race.
            with SessionLocal() as db:
                mem.cancel_memory_jobs_for_conversation(cid, db)
                db.commit()
                vectors.clear()  # successful external delete
                db.query(MemoryOutbox).filter_by(conversation_id=cid).delete()
                db.delete(db.get(Conversation, cid))
                db.commit()
            vectors[point_id] = text  # in-flight write completes afterwards
        with patch.object(mem, "extract_knowledge", return_value={"nodes": [], "edges": []}), patch.object(mem, "save_memory", side_effect=paused_upsert):
            mem.process_memory_job(jid)
        self.assertIn(jid, vectors)
        with SessionLocal() as db:
            self.assertIsNone(db.get(Conversation, cid))

    def test_recall_question_is_stored_as_assertion(self):
        _, jid = create_job(text="Siapa pacarku?")
        with patch.object(mem, "save_memory") as save:
            result = mem.process_memory_job(jid)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(save.call_args.args[1]["epistemic_status"], "user_assertion")
        self.assertEqual(save.call_args.args[0], "Siapa pacarku?")

    def test_real_assertions_are_discarded_by_question_regex(self):
        statements = ["Golongan darahku O, apa sudah tercatat?", "Project Atlas memakai PostgreSQL, bagaimana optimasinya?", "I work at Acme. Can you remember that?"]
        for statement in statements:
            with self.subTest(statement=statement), patch.object(llm, "_memory_completion") as complete:
                self.assertEqual(llm.extract_knowledge(statement), {"nodes": [], "edges": []})
                complete.assert_not_called()

    def test_empty_extractor_object_is_accepted_as_success(self):
        response = NS(choices=[NS(message=NS(content='{"unexpected": "value"}'))])
        with patch.object(llm, "_memory_completion", return_value=response):
            self.assertEqual(llm.extract_knowledge("Aku suka kopi", raise_on_error=True), {"nodes": [], "edges": []})

    def test_summary_failed_commit_loses_folded_messages(self):
        from sqlalchemy.orm import Session
        cid, _ = create_job()
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"old-{i}"} for i in range(30)]
        with SessionLocal() as db:
            c = db.get(Conversation, cid)
            c.summary = "existing summary"
            c.message_count = 40
            for i, item in enumerate(history):
                db.add(Message(conversation_id=cid, created_at=datetime.now(timezone.utc) - timedelta(days=1) + timedelta(seconds=i), **item))
            db.commit()
        real_commit = Session.commit
        commits = 0
        def commit(db):
            nonlocal commits
            commits += 1
            if commits == 2: raise RuntimeError("synthetic summary commit failure")
            return real_commit(db)
        with patch.object(Session, "commit", new=commit), patch.object(llm, "generate_session_summary", return_value="folded old-0 old-1"), patch.object(mem, "process_memory_job"):
            mem.save_interaction(cid, "new-a", "answer-a", {}, session_history=history, session_summary="existing summary")
        with SessionLocal() as db:
            next_history = mem.get_session_history(db, cid)
            summary = mem.get_session_summary(db, cid)
        with patch.object(llm, "generate_session_summary", return_value="next") as summarize, patch.object(mem, "process_memory_job"):
            mem.save_interaction(cid, "new-b", "answer-b", {}, session_history=next_history, session_summary=summary)
        folded = summarize.call_args.args[1]
        self.assertEqual([x["content"] for x in folded], ["old-2", "old-3"])
        self.assertNotIn("old-0", summary)

    def test_stale_summary_overwrites_newer_summary(self):
        cid, _ = create_job()
        with SessionLocal() as db:
            c = db.get(Conversation, cid)
            c.message_count = 40
            c.summary = "S0"
            db.commit()
        first_started, release_first = threading.Event(), threading.Event()
        errors = []
        def summarize(existing, folds):
            if folds[0]["content"] == "A":
                first_started.set()
                if not release_first.wait(5): raise RuntimeError("barrier expired")
                return "S0+A"
            return "S0+B"
        def save_a():
            try: mem.save_interaction(cid, "a", "a-reply", {}, session_history=[{"role": "user", "content": "A"}], session_summary="S0")
            except Exception as exc: errors.append(exc)
        with patch.object(llm, "generate_session_summary", side_effect=summarize), patch.object(mem, "process_memory_job"):
            worker = threading.Thread(target=save_a)
            worker.start()
            self.assertTrue(first_started.wait(5))
            mem.save_interaction(cid, "b", "b-reply", {}, session_history=[{"role": "user", "content": "B"}], session_summary="S0")
            release_first.set()
            worker.join(5)
        self.assertFalse(errors)
        with SessionLocal() as db:
            self.assertEqual(db.get(Conversation, cid).summary, "S0+A")

    def test_reindex_count_match_can_hide_missing_point(self):
        cid, jid = create_job()
        with SessionLocal() as db:
            count = db.query(MemoryOutbox).filter(MemoryOutbox.status != "cancelled").count()
        with patch.object(vec, "get_stats", return_value={"vectors": count}), patch.object(mem, "save_memory") as save:
            result = mem.reindex_vector_memory_from_outbox()
        self.assertTrue(result["skipped"])
        save.assert_not_called()

    def test_embedding_failure_is_permanently_latched(self):
        with patch.object(vec, "encoder", None), patch.object(vec, "_encoder_load_attempted", False), patch.object(vec, "VECTOR_SIZE", 0), patch.object(vec, "SentenceTransformer", side_effect=RuntimeError("temporary init failure")) as constructor:
            for _ in range(2):
                with self.assertRaises(vec.EmbeddingUnavailableError): vec._get_encoder()
            self.assertEqual(constructor.call_count, 1)

    def test_prompt_has_no_input_budget(self):
        huge = "token " * 100_000
        from schemas.chat_sch import ChatRequest
        request = ChatRequest(message=huge)
        messages = llm._build_chat_messages(request.message, MemoryContext(), [{"role": "user", "content": huge}])
        self.assertEqual(messages[-1]["content"], huge)
        self.assertEqual(messages[-2]["content"], huge)

    def test_project_keyword_blocks_generic_public_question(self):
        scope = mem._resolve_project_scope("Apa beda project management dan product management?")
        self.assertEqual(scope.status, "ambiguous")
        self.assertFalse(llm._web_tools_allowed_for_turn("Apa beda project management dan product management?", MemoryContext(project_scope=scope)))

    def test_project_recall_blocks_unrelated_public_fact_if_memory_hit_exists(self):
        ctx = MemoryContext(project_scope=ProjectScopeContext(status="resolved", project_id="p1", resolution="session"), qdrant_context=[{"content": "project lama", "score": 0.9, "project_id": "p1", "scope": "project"}])
        self.assertFalse(llm._web_tools_allowed_for_turn("Berapa harga Pertamax hari ini?", ctx))

    def test_tfidf_discards_translation_of_research_goal(self):
        hits = [WebSearchResult(title="How to reduce database latency", url="https://example.org/source", snippet="Optimize indexes to improve query performance", engine="google")]
        self.assertEqual(web._rank_results_by_tfidf(hits, "cara mempercepat basis data"), [])

    def test_sync_client_ignores_configured_llm_timeout(self):
        with patch.object(llm, "_get_llm_connection", return_value=("audit-placeholder", None)):
            client = llm.get_llm_client()
        try:
            self.assertEqual(client.timeout.read, 600)
            self.assertEqual(client.max_retries, 2)
        finally: client.close()


class AsyncAuditChecks(unittest.IsolatedAsyncioTestCase):
    async def test_stream_discards_semantic_whitespace(self):
        client = Client(plans=[plan()], parts=("hello", " ", "world", "\n", "next"))
        with patch.object(llm, "_get_llm_connection", return_value=("audit-placeholder", None)), patch.object(llm, "_create_async_llm_client", return_value=client):
            events = [e async for e in llm.generate_chat_response_stream("hi", MemoryContext())]
        text = "".join(e["delta"] for e in events if e["type"] == "delta")
        self.assertEqual(text, "helloworldnext")

    async def test_duplicate_read_url_in_one_batch_raises(self):
        from services.diagnostic_service import InternalFeatureError
        url = "https://example.org/article"
        ctx = MemoryContext(web_context=WebSearchContext(status="ok", results=[WebSearchResult(title="a", url=url)]))
        client = Client(plans=[plan(call("read_url", {"url": url}, "c1"), call("read_url", {"url": url}, "c2"))])
        with patch.object(llm, "_get_llm_connection", return_value=("audit-placeholder", None)), patch.object(llm, "_create_async_llm_client", return_value=client):
            with self.assertRaises(InternalFeatureError) as error:
                [e async for e in llm.generate_chat_response_stream("read article", ctx)]
        self.assertIn("StopIteration", error.exception.diagnostic_log)

    async def test_simple_chat_has_two_generation_calls(self):
        client = Client(plans=[NS(choices=[NS(message=NS(content="hello from planner", tool_calls=[]))], usage=None)])
        with patch.object(llm, "_get_llm_connection", return_value=("audit-placeholder", None)), patch.object(llm, "_create_async_llm_client", return_value=client):
            [e async for e in llm.generate_chat_response_stream("halo", MemoryContext())]
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn("hello from planner", json.dumps(client.calls[-1]["messages"]))

    async def test_partial_search_failure_raises_in_production_mode(self):
        class FakeHTTP:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def get(self, url, params):
                if params["q"] == "bad": raise TimeoutError("one engine call failed")
                return NS(raise_for_status=lambda: None, json=lambda: {"results": [{"title": "good", "url": "https://example.org/good", "content": "good evidence", "engine": "google"}]})
        with patch.object(web.httpx, "AsyncClient", return_value=FakeHTTP()):
            with self.assertRaises(RuntimeError):
                await web.retrieve_web_context("good", plan=web.WebSearchPlan(True, query="good", queries=("good", "bad")), raise_on_error=True)


if __name__ == "__main__":
    print("Versions:", {p: importlib.metadata.version(p) for p in ["openai", "neo4j", "qdrant-client", "SQLAlchemy", "sentence-transformers", "fastapi"]}, flush=True)
    if "--existing" in sys.argv:
        suite = unittest.TestLoader().discover(str(ROOT / "tests"), pattern="test_*.py")
    else:
        suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    engine.dispose()
    graph_guard.stop()
    network_guard.stop()
    TEMP.cleanup()
    sys.exit(not result.wasSuccessful())
