"""Regression coverage for High findings in current_ai_knowledge_graph_analysis.md."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from services import memory_service
from services.neo4j_service import Neo4jService


class _Result:
    def __init__(self, count=0):
        self.count = count

    def single(self):
        return {"count": self.count}


class _Session:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return _Result()


class _Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _service_with(session):
    service = object.__new__(Neo4jService)
    service.driver = _Driver(session)
    return service


class _MemoryJob:
    def __init__(self):
        self.id = "job-123"
        self.status = "pending"
        self.attempts = 0
        self.last_error = None


class _DbSession:
    def __init__(self, job):
        self.job = job

    def get(self, _model, _job_id):
        return self.job

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class CurrentHighMemorySafetyTests(TestCase):
    def test_consolidation_never_forgets_node_with_current_fact(self):
        session = _Session()
        service = _service_with(session)

        stats = service.consolidate_memory(days_passed=30)

        forget_query = next(query for query, _ in session.calls if "DETACH DELETE n" in query)
        self.assertIn("NOT EXISTS", forget_query)
        self.assertIn("coalesce(r.is_current, true) = true", forget_query)
        self.assertIn("protected_current_nodes", stats)

    def test_session_provenance_cleanup_only_deletes_facts_without_other_sources(self):
        session = _Session()
        service = _service_with(session)

        service.remove_conversation_provenance("session-1", ["message-1"])

        cleanup_query, cleanup_params = session.calls[0]
        delete_query = next(query for query, _ in session.calls if "DELETE r" in query)
        self.assertIn("source_conversation_ids", cleanup_query)
        self.assertIn("source_message_ids", cleanup_query)
        self.assertEqual("session-1", cleanup_params["conversation_id"])
        self.assertEqual(["message-1"], cleanup_params["source_message_ids"])
        self.assertIn("size(coalesce(r.source_conversation_ids, [])) = 0", delete_query)

    def test_qdrant_failure_does_not_block_extraction_and_graph_stage(self):
        job = _MemoryJob()
        snapshot = {
            "id": "job-123",
            "conversation_id": "conversation-1",
            "user_message_id": "message-1",
            "user_message": "Aku kerja di tempat baru",
            "assistant_response": "Oke, aku catat.",
            "session_history": [],
            "neo4j_context": [],
            "extracted_knowledge": None,
            "vector_saved": False,
            "extraction_completed": False,
            "graph_saved": False,
            "status": "pending",
            "attempts": 0,
        }

        def get_snapshot(_job_id):
            return dict(snapshot)

        def update_snapshot(_job_id, **updates):
            snapshot.update(updates)
            return dict(snapshot)

        fake_database = SimpleNamespace(SessionLocal=lambda: _DbSession(job))
        graph_merge = MagicMock()

        with patch.dict("sys.modules", {"configs.database": fake_database}), patch.object(
            memory_service, "_get_memory_job_snapshot", side_effect=get_snapshot
        ), patch.object(
            memory_service, "_update_memory_job", side_effect=update_snapshot
        ), patch.object(
            memory_service, "_memory_job_is_active", return_value=True
        ), patch.object(
            memory_service, "_finish_memory_job", return_value={"status": "failed"}
        ), patch.object(
            memory_service, "save_memory", side_effect=RuntimeError("qdrant unavailable")
        ) as save_vector, patch.object(
            memory_service,
            "extract_knowledge",
            return_value={
                "nodes": [
                    {"id": "p", "name": "nafiz"},
                    {"id": "o", "name": "beta"},
                ],
                "edges": [{"source": "p", "target": "o", "relation": "WORKS_AT"}],
            },
        ), patch.object(memory_service.neo4j_client, "merge_knowledge", graph_merge):
            result = memory_service.process_memory_job("job-123")

        self.assertEqual({"status": "failed"}, result)
        self.assertTrue(snapshot["extraction_completed"])
        self.assertTrue(snapshot["graph_saved"])
        save_vector.assert_called_once()
        self.assertEqual("job-123", save_vector.call_args.kwargs["point_id"])
        graph_merge.assert_called_once()
