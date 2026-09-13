"""Regression coverage for M01-M10 in the 2026-09-12 extreme AI audit."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock, patch
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.message import Message

from schemas.chat_sch import MemoryContext, ProjectScopeContext
from services import llm_service, memory_service, qdrant_service
from services.neo4j_service import Neo4jService


def _completion(payload):
    return NS(choices=[NS(message=NS(content=json.dumps(payload)))], usage=None)


class _Stream:
    def __init__(self, parts):
        self.parts = iter(parts)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            part = next(self.parts)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
        return NS(choices=[NS(delta=NS(content=part), finish_reason=None)], usage=None)


class _StreamingClient:
    def __init__(self, parts):
        self.parts = parts
        self.chat = NS(completions=self)

    async def create(self, **kwargs):
        if kwargs.get("stream"):
            return _Stream(self.parts)
        return NS(choices=[NS(message=NS(content=None, tool_calls=[]))], usage=None)

    async def close(self):
        return None


class _VectorClient:
    def __init__(self):
        self.points = []

    def upsert(self, *, collection_name, points):
        del collection_name
        self.points.extend(points)


class _GraphResult:
    def __init__(self, record=None, rows=None):
        self.record = record
        self.rows = rows or []

    def single(self):
        return self.record

    def __iter__(self):
        return iter(self.rows)


class _GraphSession:
    def __init__(self, person_candidates=None):
        self.calls = []
        self.person_candidates = person_candidates or []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        if "ORDER BY person.entity_key" in query:
            return _GraphResult(rows=self.person_candidates)
        if "RETURN r.fact_id AS fact_id" in query:
            return _GraphResult({"fact_id": "fact"})
        if "RETURN collect(old.fact_id)" in query:
            return _GraphResult({"fact_ids": [], "newest_event_at": 0})
        return _GraphResult()


def _graph_service(session):
    service = object.__new__(Neo4jService)
    service.driver = NS(session=lambda: session)
    return service


class _CharacterTokenizer:
    """Make token 513+ deterministic without loading model weights in unit tests."""
    def __call__(self, text, *, add_special_tokens=False, return_offsets_mapping=False, **_kwargs):
        result = {"input_ids": list(range(len(text) + (2 if add_special_tokens else 0)))}
        if return_offsets_mapping:
            result["offset_mapping"] = [(index, index + 1) for index in range(len(text))]
        return result


class ExtremeMediumAIFixTests(TestCase):
    def test_m02_mixed_assertion_questions_reach_extractor(self):
        examples = [
            "Golongan darahku O, apa sudah tercatat?",
            "Project Atlas memakai PostgreSQL, bagaimana optimasinya?",
            "I work at Acme. Can you remember that?",
            "Apa kamu ingat? Aku sekarang kerja di Acme.",
            "Apa kamu tahu golongan darahku O?",
            "Golongan darahku O?",
            "Nama startupku Apa Studio.",
        ]
        with patch.object(
            llm_service,
            "_memory_completion",
            return_value=_completion({"nodes": [], "edges": []}),
        ) as completion:
            for example in examples:
                llm_service.extract_knowledge(example, raise_on_error=True)
        self.assertEqual(len(examples), completion.call_count)

    def test_m03_only_resolved_positive_assertions_enter_vector_memory(self):
        self.assertEqual(("", []), memory_service._vector_assertion_evidence({"nodes": [], "edges": []}))
        text, spans = memory_service._vector_assertion_evidence({
            "nodes": [{"id": "p", "name": "nafiz"}, {"id": "o", "name": "acme"}],
            "edges": [{"source": "p", "target": "o", "relation": "WORKS_AT"}],
        })
        self.assertEqual("nafiz works at acme", text)
        self.assertEqual("asserted_fact", spans[0]["modality"])
        with self.assertRaisesRegex(ValueError, "classification"):
            qdrant_service.save_memory("Siapa pacarku?", {"source_role": "user"})

    def test_m03_m04_real_store_filters_legacy_evidence_and_deduplicates_chunks(self):
        client = QdrantClient(location=":memory:")
        try:
            client.create_collection(
                collection_name=qdrant_service.COLLECTION_NAME,
                vectors_config=VectorParams(size=2, distance=Distance.COSINE),
            )
            base = {"source_role": "user", "epistemic_status": "user_assertion", "scope": "global",
                    "embedding_signature": qdrant_service.embedding_signature()}
            client.upsert(collection_name=qdrant_service.COLLECTION_NAME, points=[
                PointStruct(id=str(uuid.uuid4()), vector=[1.0, 0.0], payload={**base,
                    "text": "legacy question", "message_id": "legacy"}),
                PointStruct(id=str(uuid.uuid4()), vector=[1.0, 0.0], payload={**base,
                    "evidence_version": 2, "text": "awal pesan", "message_id": "one"}),
                PointStruct(id=str(uuid.uuid4()), vector=[1.0, 0.0], payload={**base,
                    "evidence_version": 2, "text": "fakta tailunique", "message_id": "one"}),
                PointStruct(id=str(uuid.uuid4()), vector=[1.0, 0.0], payload={**base,
                    "evidence_version": 2, "text": "fakta pesan lainnya", "message_id": "two"}),
            ])
            with patch.object(qdrant_service, "client", client), patch.object(
                qdrant_service, "embed_text", return_value=[1.0, 0.0]
            ):
                hits = qdrant_service.search_memory("tailunique", limit=3)
            self.assertEqual(["one", "two"], [hit["message_id"] for hit in hits])
            self.assertEqual("fakta tailunique", hits[0]["content"])
        finally:
            client.close()

    def test_m04_long_memory_is_chunked_through_its_tail(self):
        client = _VectorClient()
        text = ("awal keputusan arsitektur " * 100) + "FAKTA_EKOR_UNIK"
        with patch.object(qdrant_service, "client", client), patch.object(
            qdrant_service, "embed_texts", side_effect=lambda texts, **_kwargs: [[0.1, 0.2] for _ in texts]
        ), patch.object(qdrant_service, "_get_encoder", return_value=NS(
            tokenizer=_CharacterTokenizer(), max_seq_length=512
        )):
            qdrant_service.save_memory(text, {
                "epistemic_status": "user_assertion",
                "assertion_spans": [{"text": text, "modality": "asserted_fact", "polarity": "positive"}],
            }, point_id=str(uuid.uuid4()))
        self.assertGreater(len(client.points), 1)
        self.assertIn("FAKTA_EKOR_UNIK", client.points[-1].payload["text"])
        self.assertEqual(len(client.points), len({point.id for point in client.points}))
        self.assertTrue(all("span_start" in point.payload for point in client.points))
        self.assertTrue(all(len(point.payload["text"]) <= 440 for point in client.points))

    def test_m04_slow_tokenizer_fallback_still_enforces_real_window(self):
        class SlowTokenizer(_CharacterTokenizer):
            def __call__(self, text, *, return_offsets_mapping=False, **kwargs):
                if return_offsets_mapping:
                    raise NotImplementedError("slow tokenizer")
                return super().__call__(text, **kwargs)
        tokenizer = SlowTokenizer()
        text = "fakta panjang " * 300 + "FAKTA_EKOR_UNIK"
        with patch.object(qdrant_service, "_get_encoder", return_value=NS(
            tokenizer=tokenizer, max_seq_length=128
        )):
            offsets = qdrant_service._memory_chunk_offsets(text)
        self.assertIn("FAKTA_EKOR_UNIK", text[offsets[-1][0]:offsets[-1][1]])
        self.assertTrue(all(
            len(tokenizer(qdrant_service._embedding_input(text[start:end], "passage"),
                          add_special_tokens=True)["input_ids"]) <= 128
            for start, end in offsets
        ))

    def test_m05_graph_search_batches_keywords_and_ranks_joint_matches(self):
        session = _GraphSession()
        _graph_service(session).search_knowledge(["nafiz", "works at"])
        self.assertEqual(1, len(session.calls))
        query, params = session.calls[0]
        self.assertIn("entity_identity_search", query)
        self.assertIn("entity_score > 0 AND relation_score > 0", query)
        self.assertEqual(2, len(params["prepared_keywords"]))

    def test_m06_invalid_extraction_envelope_is_retryable_error(self):
        with patch.object(
            llm_service, "_memory_completion", return_value=_completion({"unexpected": "value"})
        ):
            with self.assertRaisesRegex(ValueError, "missing required 'nodes'"):
                llm_service.extract_knowledge("Aku suka kopi", raise_on_error=True)

    def test_m06_invalid_root_and_array_items_cannot_be_sanitized_to_success(self):
        invalid_outputs = [
            [{"nodes": [], "edges": []}],
            {"nodes": {}, "edges": []},
            {"nodes": [], "edges": [None]},
            {"nodes": [], "edges": [], "retractions": [False]},
        ]
        for payload in invalid_outputs:
            with self.subTest(payload=payload), patch.object(
                llm_service, "_memory_completion", return_value=_completion(payload)
            ):
                with self.assertRaises(ValueError):
                    llm_service.extract_knowledge("Aku suka kopi", raise_on_error=True)

    def test_m07_public_project_concept_and_live_question_keep_public_path(self):
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = []
        with patch("configs.database.SessionLocal", return_value=db):
            scope = memory_service._resolve_project_scope(
                "Apa beda project management dan product management?"
            )
        self.assertEqual("none", scope.status)
        context = MemoryContext(
            project_scope=ProjectScopeContext(
                status="resolved", project_id="p1", project_name="Atlas", resolution="session"
            ),
            qdrant_context=[{
                "content": "project lama", "score": 0.9, "project_id": "p1",
                "scope": "project", "source_role": "user", "epistemic_status": "user_assertion",
            }],
        )
        self.assertTrue(llm_service._web_tools_allowed_for_turn("Berapa harga Pertamax hari ini?", context))
        self.assertTrue(llm_service._web_tools_allowed_for_turn(
            "Berapa harga AWS terbaru untuk project Atlas?", context
        ))

    def test_m08_external_project_does_not_collapse_into_active_project(self):
        session = _GraphSession()
        _graph_service(session).merge_knowledge(
            [
                {"id": "a", "label": "Project", "name": "atlas", "identity_context": "p-atlas"},
                {"id": "b", "label": "Project", "name": "boreal"},
            ],
            [{"source": "a", "target": "b", "relation": "DEPENDS_ON"}],
            project_id="p-atlas",
            project_name="Atlas",
        )
        params = next(params for query, params in session.calls if "MERGE (a)-[r:DEPENDS_ON" in query)
        self.assertNotEqual(params["source"], params["target"])

    def test_m08_extractor_preserves_external_project_even_when_it_is_first(self):
        payload = {
            "nodes": [
                {"id": "b", "label": "Project", "name": "boreal"},
                {"id": "a", "label": "Project", "name": "atlas"},
            ],
            "edges": [{"source": "a", "target": "b", "relation": "DEPENDS_ON"}],
        }
        with patch.object(llm_service, "_memory_completion", return_value=_completion(payload)):
            extracted = llm_service.extract_knowledge(
                "Atlas bergantung pada project Boreal", project_id="p-atlas", project_name="Atlas",
                raise_on_error=True,
            )
        self.assertEqual("boreal", extracted["nodes"][0]["name"])
        self.assertEqual("p-atlas", extracted["nodes"][1]["identity_context"])

    def test_m09_identity_paraphrases_share_canonical_key(self):
        self.assertEqual(
            Neo4jService._entity_key("Person", "siska", "ibu nafiz"),
            Neo4jService._entity_key("Person", "siska", "ibu dari nafiz"),
        )
        self.assertNotEqual(
            Neo4jService._entity_key("Person", "siska", "ibu nafiz"),
            Neo4jService._entity_key("Person", "siska", "teman kerja nafiz"),
        )

    def test_m09_linking_reuses_unique_legacy_node_and_records_decision(self):
        session = _GraphSession(person_candidates=[{
            "entity_key": "person:legacy-hash", "identity_context": "ibu dari nafiz",
            "identity_signature": None,
        }])
        _graph_service(session).merge_knowledge(
            [{"id": "s", "label": "Person", "name": "siska", "identity_context": "ibu nafiz"}],
            [],
        )
        node = next(params for query, params in session.calls if "MERGE (n:Entity" in query)
        self.assertEqual("person:legacy-hash", node["entity_key"])
        self.assertTrue(any("MERGE (i)-[:RESOLVES_TO]" in query for query, _ in session.calls))

    def test_m09_ambiguous_existing_nodes_are_quarantined(self):
        session = _GraphSession(person_candidates=[
            {"entity_key": key, "identity_context": "ibu nafiz", "identity_signature": None}
            for key in ("person:one", "person:two")
        ])
        result = _graph_service(session).merge_knowledge(
            [{"id": "s", "label": "Person", "name": "siska", "identity_context": "ibu nafiz"}],
            [], source_message_id="new-message",
        )
        self.assertEqual(["new-message"], result["invalidated_source_message_ids"])
        self.assertFalse(any("MERGE (n:Entity" in query for query, _ in session.calls))

    def test_m10_embedding_initialization_retries_after_backoff(self):
        model = MagicMock()
        model.get_sentence_embedding_dimension.return_value = 2
        with patch.object(qdrant_service, "encoder", None), patch.object(
            qdrant_service, "_encoder_load_attempted", False
        ), patch.object(qdrant_service, "_encoder_failure_count", 0), patch.object(
            qdrant_service, "_encoder_next_retry_at", 0.0
        ), patch.object(qdrant_service.settings, "EMBEDDING_INIT_RETRY_BASE_SECONDS", 1.0), patch.object(
            qdrant_service, "SentenceTransformer", side_effect=[RuntimeError("temporary"), model]
        ) as constructor, patch.object(qdrant_service, "_ensure_collection"):
            with patch.object(qdrant_service.time, "monotonic", return_value=0.0):
                with self.assertRaises(qdrant_service.EmbeddingUnavailableError):
                    qdrant_service._get_encoder()
                with self.assertRaises(qdrant_service.EmbeddingUnavailableError):
                    qdrant_service._get_encoder()
            with patch.object(qdrant_service.time, "monotonic", return_value=2.0):
                self.assertIs(model, qdrant_service._get_encoder())
        self.assertEqual(2, constructor.call_count)

    def test_m10_store_retry_reuses_model_weights(self):
        model = NS(get_sentence_embedding_dimension=lambda: 2)
        with patch.object(qdrant_service, "encoder", None), patch.object(
            qdrant_service, "_pending_encoder", None
        ), patch.object(qdrant_service, "_encoder_load_attempted", False), patch.object(
            qdrant_service, "_encoder_failure_count", 0
        ), patch.object(qdrant_service, "_encoder_next_retry_at", 0.0), patch.object(
            qdrant_service.settings, "EMBEDDING_INIT_RETRY_BASE_SECONDS", 1.0
        ), patch.object(qdrant_service, "SentenceTransformer", return_value=model) as constructor, patch.object(
            qdrant_service, "_ensure_collection", side_effect=[RuntimeError("store unavailable"), None]
        ):
            with patch.object(qdrant_service.time, "monotonic", return_value=0.0):
                with self.assertRaises(qdrant_service.EmbeddingUnavailableError):
                    qdrant_service._get_encoder()
            with patch.object(qdrant_service.time, "monotonic", return_value=2.0):
                self.assertIs(model, qdrant_service._get_encoder())
        constructor.assert_called_once()

    def test_m06_failed_extraction_keeps_vector_stage_pending_for_retry(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with sessions() as db:
                conversation = Conversation(title="Test")
                db.add(conversation)
                db.flush()
                message = Message(conversation_id=conversation.id, role="user", content="Aku kerja di Acme")
                db.add(message)
                db.flush()
                job = MemoryOutbox(conversation_id=conversation.id, user_message_id=message.id,
                                   user_message=message.content, assistant_response="Oke")
                db.add(job)
                db.commit()
                job_id = job.id
            with patch("configs.database.SessionLocal", sessions), patch.object(
                memory_service, "extract_knowledge", side_effect=ValueError("invalid_output")
            ), patch.object(memory_service, "save_memory") as save:
                memory_service.process_memory_job(job_id)
                save.assert_not_called()
            with sessions() as db:
                job = db.get(MemoryOutbox, job_id)
                self.assertFalse(job.vector_saved)
                job.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
            with patch("configs.database.SessionLocal", sessions), patch.object(
                memory_service, "extract_knowledge", return_value={
                    "nodes": [{"id": "p", "name": "nafiz"}, {"id": "o", "name": "acme"}],
                    "edges": [{"source": "p", "target": "o", "relation": "WORKS_AT"}],
                }
            ), patch.object(memory_service, "save_memory") as save, patch.object(
                memory_service.neo4j_client, "merge_knowledge", return_value={}
            ):
                memory_service.process_memory_job(job_id)
                save.assert_called_once()
        finally:
            engine.dispose()


class ExtremeMediumAIStreamFixTests(IsolatedAsyncioTestCase):
    async def test_m01_stream_preserves_semantic_whitespace(self):
        client = _StreamingClient(("hello", " ", "world", "\n", "next"))
        with patch.object(llm_service, "_get_llm_connection", return_value=("model", None)), patch.object(
            llm_service, "_create_async_llm_client", return_value=client
        ):
            events = [event async for event in llm_service.generate_chat_response_stream(
                "hi", MemoryContext()
            )]
        self.assertEqual(
            "hello world\nnext",
            "".join(event["delta"] for event in events if event["type"] == "delta"),
        )
