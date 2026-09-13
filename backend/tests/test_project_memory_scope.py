from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from schemas.chat_sch import MemoryContext, ProjectScopeContext
from services import llm_service, memory_service, qdrant_service


class _SearchClient:
    def __init__(self):
        self.kwargs = None

    def query_points(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    score=0.9,
                    payload={
                        "text": "backend memakai PostgreSQL",
                        "project_id": "prj-a",
                        "scope": "project",
                    },
                )
            ]
        )


class _ExtractionClient:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = (
            '{"nodes": ['
            '{"id":"tech","label":"Technology","name":"postgresql","identity_context":"","confidence":1.0},'
            '{"id":"app","label":"Technology","name":"backend","identity_context":"","confidence":1.0}'
            '],"edges":[{"source":"app","target":"tech","relation":"USES_TECH",'
            '"supersedes":[],"replaces_current_relation":false,"confidence":1.0}]}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=None,
        )


class ProjectMemoryScopeTests(TestCase):
    @staticmethod
    def _project_db(projects):
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = projects
        return db

    def test_global_reference_resolves_named_project_before_retrieval(self):
        projects = [
            SimpleNamespace(id="prj-a", name="TCMudah", updated_at=None),
            SimpleNamespace(id="prj-b", name="Project Magang", updated_at=None),
        ]
        db = self._project_db(projects)
        with patch("configs.database.SessionLocal", return_value=db):
            scope = memory_service._resolve_project_scope(
                "di TCMudah perhitungan pajaknya gimana?"
            )

        self.assertEqual("resolved", scope.status)
        self.assertEqual("prj-a", scope.project_id)
        self.assertEqual("message", scope.resolution)

    def test_semantic_resolution_falls_back_to_clarification_when_scores_are_close(self):
        projects = [
            SimpleNamespace(id="prj-a", name="TCMudah", updated_at=None),
            SimpleNamespace(id="prj-b", name="Project Magang", updated_at=None),
        ]
        db = self._project_db(projects)
        evidence = [
            {"project_id": "prj-a", "score": 0.86, "content": "perhitungan pajak"},
            {"project_id": "prj-b", "score": 0.84, "content": "perhitungan biaya"},
        ]
        with patch("configs.database.SessionLocal", return_value=db), patch.object(
            memory_service, "search_project_memory_candidates", return_value=evidence
        ):
            scope = memory_service._resolve_project_scope(
                "eh di project-ku itu perhitungannya gimana?"
            )

        self.assertEqual("ambiguous", scope.status)
        self.assertEqual(["TCMudah", "Project Magang"], scope.candidates)

    def test_ambiguous_project_prompt_requires_one_clarifying_question(self):
        context = MemoryContext(
            project_scope=ProjectScopeContext(
                status="ambiguous",
                candidates=["TCMudah", "Project Magang"],
            )
        )
        prompt = llm_service._build_chat_messages(
            "di project-ku itu perhitungannya gimana?",
            context,
        )[0]["content"]

        self.assertIn("<ambiguous_project_reference_json>", prompt)
        self.assertIn("Jangan menebak project", prompt)
        self.assertIn("Jangan mencari jawabannya di web", prompt)

    def test_inferred_project_turn_blocks_web_unless_explicitly_requested(self):
        inferred = MemoryContext(
            project_scope=ProjectScopeContext(
                status="resolved",
                project_id="prj-a",
                project_name="TCMudah",
                resolution="semantic",
            )
        )
        self.assertFalse(
            llm_service._web_tools_allowed_for_turn(
                "di project-ku perhitungan pajaknya gimana?",
                inferred,
            )
        )
        self.assertTrue(
            llm_service._web_tools_allowed_for_turn(
                "cari di Google referensi pajak terbaru untuk project-ku",
                inferred,
            )
        )

    def test_active_project_still_allows_unrelated_live_research(self):
        active = MemoryContext(
            project_scope=ProjectScopeContext(
                status="resolved",
                project_id="prj-a",
                project_name="TCMudah",
                resolution="session",
            )
        )
        self.assertTrue(
            llm_service._web_tools_allowed_for_turn(
                "berapa harga Pertamax hari ini?",
                active,
            )
        )
        self.assertFalse(
            llm_service._web_tools_allowed_for_turn(
                "perhitungan di project ini gimana?",
                active,
            )
        )

    def test_extractor_discards_unknown_provider_metadata_without_losing_fact(self):
        sanitized = llm_service._sanitize_extracted_knowledge(
            {
                "nodes": [
                    {
                        "id": "app",
                        "label": "Technology",
                        "name": "backend",
                        "confidence": 1.0,
                        "comment": "provider-added metadata",
                    },
                    {
                        "id": "db",
                        "label": "Technology",
                        "name": "postgresql",
                        "confidence": 1.0,
                    },
                ],
                "edges": [
                    {
                        "source": "app",
                        "target": "db",
                        "relation": "USES_TECH",
                        "confidence": 1.0,
                        "note": "project magang",
                    }
                ],
            }
        )

        validated = llm_service.validate_extracted_knowledge(sanitized)
        self.assertNotIn("comment", validated["nodes"][0])
        self.assertNotIn("note", validated["edges"][0])
        self.assertEqual("USES_TECH", validated["edges"][0]["relation"])

    def test_qdrant_project_filter_allows_only_active_project_or_global(self):
        fake_client = _SearchClient()
        with patch.object(qdrant_service, "client", fake_client), patch.object(
            qdrant_service, "embed_text", return_value=[0.1, 0.2]
        ):
            result = qdrant_service.search_memory("database backend", project_id="prj-a")

        should = fake_client.kwargs["query_filter"].should
        project_conditions = [item for item in should if hasattr(item, "key")]
        values = {item.match.value for item in project_conditions}
        self.assertEqual({"prj-a", "global"}, values)
        self.assertEqual("prj-a", result[0]["project_id"])
        self.assertEqual("project", result[0]["scope"])

    def test_project_forces_scoped_retrieval_even_when_router_says_not_needed(self):
        route = llm_service.MemoryRouteDecision("not_needed", [])
        with patch.object(memory_service, "route_memory_query", return_value=route), patch.object(
            memory_service, "search_memory", return_value=[]
        ) as vector_search, patch.object(
            memory_service.neo4j_client, "search_knowledge", return_value=[]
        ) as graph_search:
            context = memory_service.retrieve_context("lanjut bagian database", project_id="prj-a")

        self.assertEqual("forced", context.retrieval_status.router)
        self.assertEqual("prj-a", vector_search.call_args.kwargs["project_id"])
        self.assertEqual("prj-a", graph_search.call_args.kwargs["project_id"])

    def test_prompt_and_extractor_receive_active_project(self):
        prompt = llm_service._build_chat_messages(
            "lanjut",
            MemoryContext(),
            project_id="prj-a",
            project_name="TCMudah",
        )[0]["content"]
        self.assertIn("<active_project_json>", prompt)
        self.assertIn("TCMudah", prompt)
        self.assertIn("Jangan mencampurkan detail dari project lain", prompt)

        client = _ExtractionClient()
        with patch.object(llm_service, "get_llm_client", return_value=client):
            extracted = llm_service.extract_knowledge(
                "backend memakai PostgreSQL",
                project_id="prj-a",
                project_name="TCMudah",
            )

        project_nodes = [node for node in extracted["nodes"] if node["label"] == "Project"]
        self.assertEqual(1, len(project_nodes))
        self.assertTrue(any(edge["relation"] == "BELONGS_TO" for edge in extracted["edges"]))
