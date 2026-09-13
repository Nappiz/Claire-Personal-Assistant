"""Regression tests for the three Critical memory-correctness issues."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from schemas.chat_sch import MemoryContext
from services import llm_service, memory_service, qdrant_service
from services.neo4j_service import Neo4jService


class _FakeQdrantClient:
    def __init__(self):
        self.points = []

    def upsert(self, *, collection_name, points):
        self.points.extend(points)


class _FakeExtractionClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class CriticalMemorySafetyTests(TestCase):
    def test_repeated_short_messages_receive_distinct_qdrant_points(self):
        """Repeated text must not overwrite an earlier interaction."""
        fake_client = _FakeQdrantClient()
        with patch.object(qdrant_service, "client", fake_client), patch.object(
            qdrant_service, "embed_text", return_value=[0.0] * qdrant_service.VECTOR_SIZE
        ), patch.object(
            qdrant_service, "_memory_chunk_offsets", side_effect=lambda text: [(0, len(text))]
        ):
            evidence = {
                "epistemic_status": "user_assertion",
                "assertion_spans": [{"text": "halo", "modality": "asserted_fact", "polarity": "positive"}],
            }
            first_id = qdrant_service.save_memory("halo", {**evidence, "session_id": "day-1"}, dedup_key="halo")
            second_id = qdrant_service.save_memory("halo", {**evidence, "session_id": "day-8"}, dedup_key="halo")

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(2, len(fake_client.points))
        self.assertNotEqual(fake_client.points[0].id, fake_client.points[1].id)
        self.assertEqual(
            fake_client.points[0].payload["interaction_fingerprint"],
            fake_client.points[1].payload["interaction_fingerprint"],
        )
        self.assertEqual("user", fake_client.points[0].payload["source_role"])

    def test_people_with_same_name_need_distinct_contextual_identity(self):
        mother = Neo4jService._entity_key("Person", "siska", "ibu nafiz")
        friend_wife = Neo4jService._entity_key("Person", "siska", "istri budi, dokter gigi")

        self.assertNotEqual(mother, friend_wife)
        with self.assertRaises(ValueError):
            Neo4jService._entity_key("Person", "siska")

    def test_extractor_receives_history_and_rejects_generic_pronoun_node(self):
        fake_client = _FakeExtractionClient(
            '{"nodes": [{"id": "p1", "label": "Person", "name": "dia"}], '
            '"edges": [{"source": "p1", "target": "telkomsel", "relation": "WORKS_AT"}]}'
        )
        history = [
            {"role": "user", "content": "Aku cerita soal Cia tadi."},
            {"role": "assistant", "content": "Cia kerja di mana sekarang?"},
        ]

        with patch.object(llm_service, "get_llm_client", return_value=fake_client):
            result = llm_service.extract_knowledge(
                "di Telkomsel, dia baru masuk bulan lalu",
                session_history=history,
            )

        prompt = fake_client.calls[0]["messages"][0]["content"]
        self.assertIn("<recent_conversation>", prompt)
        self.assertIn("Cia kerja di mana sekarang?", prompt)
        self.assertEqual({"nodes": [], "edges": []}, result)

    def test_memory_and_focus_policy_share_one_system_message(self):
        fake_client = _FakeExtractionClient("jawaban terbaru")
        with patch.object(llm_service, "get_llm_client", return_value=fake_client):
            reply, _ = llm_service.generate_chat_response(
                "kamu tau ga claire siapa yang nyiptain kamu?",
                MemoryContext(qdrant_context=[{
                    "content": "Siska adalah ibu saya.",
                    "score": 0.91,
                    "source_role": "user",
                    "epistemic_status": "user_assertion",
                }]),
                session_history=[
                    {"role": "user", "content": "kamu tau ga siska itu siapa ku?"},
                    {"role": "assistant", "content": "Siska ibu kamu."},
                ],
            )

        messages = fake_client.calls[0]["messages"]
        self.assertEqual("jawaban terbaru", reply)
        system_messages = [message for message in messages if message["role"] == "system"]
        self.assertEqual(1, len(system_messages))
        self.assertIn("ATURAN FINAL UNTUK TURN AKTIF", system_messages[0]["content"])
        self.assertIn("Siska adalah ibu saya", system_messages[0]["content"])
        self.assertEqual("kamu tau ga claire siapa yang nyiptain kamu?", messages[-1]["content"])

    def test_personal_intent_adds_exact_graph_relation_hints(self):
        route = llm_service.MemoryRouteDecision(status="not_needed", keywords=[])
        with patch.object(memory_service, "route_memory_query", return_value=route), patch.object(
            memory_service, "search_memory", return_value=[]
        ), patch.object(
            memory_service.neo4j_client,
            "search_knowledge",
            return_value=["nafiz works at agung sedayu group"],
        ) as graph_search:
            context = memory_service.retrieve_context("aku kerja dimana")

        searched_keywords = graph_search.call_args.args[0]
        self.assertIn("works at", searched_keywords)
        self.assertIn("nafiz", searched_keywords)
        self.assertEqual(["nafiz works at agung sedayu group"], context.neo4j_context)

    def test_recall_questions_are_never_written_back_as_new_facts(self):
        recall_questions = [
            "siapa pacarku?",
            "aku kerja dimana",
            "kamu inget ga aku pernah ngomong tanggal lahir ku",
            "lah kan kamu tau pacarku",
            "eh claire harga rumah di Surabaya sekitar Pakuwon City berapa sih?",
            "mahal juga yak, kalau daerah yang lebih murah tuh daerah mana",
        ]
        with patch.object(llm_service, "get_llm_client") as client:
            results = [llm_service.extract_knowledge(message) for message in recall_questions]

        self.assertEqual([{"nodes": [], "edges": []}] * len(recall_questions), results)
        client.assert_not_called()

    def test_public_housing_question_does_not_force_personal_memory_lookup(self):
        route = llm_service.MemoryRouteDecision(status="not_needed", keywords=[])
        with patch.object(memory_service, "route_memory_query", return_value=route), patch.object(
            memory_service, "search_memory"
        ) as qdrant_search, patch.object(memory_service.neo4j_client, "search_knowledge") as graph_search:
            context = memory_service.retrieve_context(
                "harga rumah di Surabaya sekitar Pakuwon City berapa sih?"
            )

        self.assertEqual("not_needed", context.retrieval_status.router)
        qdrant_search.assert_not_called()
        graph_search.assert_not_called()

    def test_multi_value_replace_flag_is_safely_normalized(self):
        sanitized = llm_service._sanitize_extracted_knowledge(
            {
                "nodes": [
                    {"id": "p_nafiz", "label": "Person", "name": "nafiz"},
                    {"id": "topic", "label": "Concept", "name": "rumah"},
                ],
                "edges": [
                    {
                        "source": "p_nafiz",
                        "target": "topic",
                        "relation": "DISCUSSING",
                        "supersedes": [],
                        "replaces_current_relation": True,
                    }
                ],
            }
        )

        self.assertFalse(sanitized["edges"][0]["replaces_current_relation"])
        self.assertEqual(
            "DISCUSSING",
            llm_service.validate_extracted_knowledge(sanitized)["edges"][0]["relation"],
        )

    def test_no_memory_search_runs_when_router_says_question_is_standalone(self):
        with patch.object(memory_service, "route_memory_query") as router, patch.object(
            memory_service, "search_memory"
        ) as qdrant_search, patch.object(memory_service.neo4j_client, "search_knowledge") as graph_search:
            context = memory_service.retrieve_context("kamu tau ga claire siapa yang nyiptain kamu?")

        self.assertEqual([], context.qdrant_context)
        self.assertEqual([], context.neo4j_context)
        router.assert_not_called()
        qdrant_search.assert_not_called()
        graph_search.assert_not_called()
