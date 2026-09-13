"""HTTP contracts and side-effect order on isolated SQLAlchemy/fake provider adapters."""
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.api import dependencies
from app.infrastructure import application_wiring as bridges
from models import Base
from models.conversation import Conversation
from models.message import Message
from schemas.chat_sch import MemoryContext
from test_api_contract import published_api


class RefactoredHTTPTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.api = published_api()

        def isolated_db():
            with self.sessions() as db:
                yield db

        self.api.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(self.api)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def conversation(self, title="Chat"):
        with self.sessions() as db:
            row = Conversation(title=title)
            db.add(row)
            db.commit()
            return row.id

    def test_project_crud_normalizes_values_and_keeps_duplicate_conflict(self):
        response = self.client.post("/api/v1/projects", json={"name": "  My   Project ", "description": " description "})
        self.assertEqual(201, response.status_code)
        data = response.json()
        self.assertEqual("My Project", data["name"])
        self.assertEqual("description", data["description"])
        duplicate = self.client.post("/api/v1/projects", json={"name": "My Project"})
        self.assertEqual(409, duplicate.status_code)
        self.assertEqual("Project name already exists", duplicate.json()["detail"])
        edited = self.client.patch(f"/api/v1/projects/{data['id']}", json={"description": " "})
        self.assertIsNone(edited.json()["description"])
        self.assertEqual(1, len(self.client.get("/api/v1/projects").json()))
        self.assertEqual({"message": "Project deleted"}, self.client.delete(f"/api/v1/projects/{data['id']}").json())

    def test_project_with_live_conversation_cannot_be_deleted(self):
        project = self.client.post("/api/v1/projects", json={"name": "Used"}).json()
        with self.sessions() as db:
            db.add(Conversation(title="Live", project_id=project["id"]))
            db.commit()
        response = self.client.delete(f"/api/v1/projects/{project['id']}")
        self.assertEqual(409, response.status_code)

    def test_pin_history_and_missing_session_contracts(self):
        session = self.conversation()
        response = self.client.patch(f"/api/v1/sessions/{session}/pin", json={"is_pinned": True})
        self.assertTrue(response.json()["is_pinned"])
        self.assertTrue(self.client.get("/api/v1/sessions").json()[0]["is_pinned"])
        self.assertEqual([], self.client.get(f"/api/v1/history/{session}").json())
        self.assertEqual(404, self.client.get("/api/v1/history/missing").status_code)

    def test_delete_failure_tombstones_before_cleanup_and_retry_keeps_order(self):
        session = self.conversation()
        with self.sessions() as db:
            db.add(Message(conversation_id=session, role="user", content="My assertion"))
            db.commit()
        calls = []

        def graph_cleanup(*_args):
            with self.sessions() as db:
                self.assertIsNotNone(db.get(Conversation, session).deleted_at)
            calls.append("graph")
            if len(calls) == 1:
                raise RuntimeError("graph unavailable")
            return {"facts_deleted": 1}

        graph = NS(remove_conversation_provenance=graph_cleanup)
        vector = NS(delete_memory_by_session=lambda _: calls.append("vector"))
        with patch.object(bridges, "graph_store", graph), patch.object(bridges, "vector_store", vector):
            failed = self.client.delete(f"/api/v1/sessions/{session}")
            self.assertEqual(502, failed.status_code)
            with self.sessions() as db:
                self.assertEqual(1, db.query(Message).count())
            self.assertEqual(404, self.client.get(f"/api/v1/history/{session}").status_code)
            retried = self.client.delete(f"/api/v1/sessions/{session}")
            self.assertEqual(200, retried.status_code)
        self.assertEqual(["graph", "graph", "vector"], calls)
        with self.sessions() as db:
            self.assertEqual(0, db.query(Message).count())
            self.assertEqual("Deleted session", db.get(Conversation, session).title)

    def test_graph_fact_lifecycle_propagates_to_source_and_vector(self):
        graph = NS(update_fact=lambda *_: {"source_message_ids": ["source-1"], "is_current": False})
        vector = Mock()
        with patch.object(bridges, "graph_store", graph), patch.object(bridges, "vector_store", vector), patch.object(
            bridges.memory_workflows, "set_source_messages_memory_status", return_value=1
        ) as source_status:
            response = self.client.patch("/api/v1/memory/graph/fact/fact-1", json={"is_current": False})
        self.assertEqual(200, response.status_code)
        source_status.assert_called_once_with(["source-1"], "inactive")
        vector.set_memories_status.assert_called_once_with(["source-1"], status="inactive")

    def test_graph_query_bounds_and_error_mapping(self):
        self.assertEqual(422, self.client.get("/api/v1/memory/graph?limit=1001").status_code)
        graph = Mock()
        graph.update_node.side_effect = ValueError("The corrected identity already exists")
        with patch.object(bridges, "graph_store", graph):
            response = self.client.patch("/api/v1/memory/graph/node/person:test", json={"name": "Other"})
        self.assertEqual(409, response.status_code)

    def test_settings_mask_keys_and_reveal_disables_cache(self):
        response = self.client.post("/api/v1/settings", json={"key": "api_keys", "value": {"google": "test-secret"}})
        self.assertEqual({"google": {"configured": True}}, response.json()["value"])
        self.assertNotIn("test-secret", self.client.get("/api/v1/settings/api_keys").text)
        reveal = self.client.get("/api/v1/settings/api_keys/reveal")
        self.assertEqual("no-store, private", reveal.headers["cache-control"])
        self.assertEqual({"google": "test-secret"}, reveal.json()["value"])

    def test_sse_provider_timeout_keeps_partial_delta_and_terminal_error(self):
        async def stream(*_args, **_kwargs):
            yield {"type": "delta", "delta": "Partial"}
            raise TimeoutError("provider timeout")

        with patch.object(dependencies, "_prepare_stream_session", return_value=("s-1", False, [], "", None, None, "turn-1", {"completed": False})), patch.object(
            bridges.memory_workflows, "retrieve_context", return_value=MemoryContext()
        ), patch.object(bridges.llm_workflows, "generate_chat_response_stream", stream), patch.object(
            bridges.memory_workflows, "mark_turn_status"
        ) as status:
            response = self.client.post("/api/v1/chat/stream", json={"message": "Hello"})
        import json
        events = [json.loads(frame[6:]) for frame in response.text.strip().split("\n\n")]
        self.assertEqual(["session", "delta", "error"], [event["type"] for event in events])
        self.assertEqual("UPSTREAM_TIMEOUT", events[-1]["error"]["code"])
        self.assertEqual("turn-1", events[-1]["turn_id"])
        self.assertEqual("no-cache, no-transform", response.headers["cache-control"])
        status.assert_called_once()
