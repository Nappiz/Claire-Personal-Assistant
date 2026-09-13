from datetime import datetime, timezone
from types import SimpleNamespace as Record
from unittest import TestCase
from unittest.mock import Mock

from app.domain.llm.contracts import MemoryLLMUnavailableError
from test_memory_read_boundaries import fake_memory


def outbox_workflow():
    workflow = fake_memory()
    snapshot = dict(id="j1", conversation_id="s1", user_message_id="m1",
                    user_message="aku kerja di Acme", neo4j_context=[], session_history=[],
                    vector_saved=False, graph_saved=False, extraction_completed=False,
                    extracted_knowledge=None, created_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
                    event_at=datetime(2026, 9, 13, tzinfo=timezone.utc), attempts=1)
    workflow.claim_memory_job = Mock(return_value="lease1")
    workflow.leased_memory_job_snapshot = Mock(side_effect=lambda *args: dict(snapshot))
    workflow.memory_job_is_active = Mock(return_value=True)
    workflow.update_memory_job = Mock(side_effect=lambda job_id, **values: snapshot.update({key: value for key, value in values.items() if key != "expected_lease_token"}))
    workflow.finish_memory_job = Mock(side_effect=lambda *args: {"status": "completed" if all(snapshot[key] for key in ("vector_saved", "graph_saved", "extraction_completed")) else "failed"})
    workflow.cancel_claim = Mock(return_value={"status": "cancelled"})
    workflow.extract_knowledge = Mock(return_value={"nodes": [
        {"id": "p", "name": "nafiz", "label": "Person"},
        {"id": "o", "name": "Acme", "label": "Organization"}],
        "edges": [{"source": "p", "target": "o", "relation": "WORKS_AT"}]})
    workflow.graph.merge_knowledge.return_value = {}
    return workflow, snapshot


class MemoryOutboxBoundaryTests(TestCase):
    def test_provider_down_keeps_job_retryable_and_prevents_invalid_writes(self):
        workflow, snapshot = outbox_workflow()
        workflow.extract_knowledge.side_effect = MemoryLLMUnavailableError("provider offline")
        result = workflow.process_memory_job("j1", report_errors=True)
        self.assertEqual("failed", result["status"])
        self.assertFalse(snapshot["extraction_completed"])
        self.assertIn("provider offline", workflow.finish_memory_job.call_args.args[2][0])
        workflow.save_memory.assert_not_called()
        workflow.graph.merge_knowledge.assert_not_called()

    def test_partial_vector_failure_retries_same_id_without_duplicate_graph(self):
        workflow, snapshot = outbox_workflow()
        workflow.save_memory.side_effect = [RuntimeError("vector offline"), "j1"]
        self.assertEqual("failed", workflow.process_memory_job("j1")["status"])
        self.assertTrue(snapshot["graph_saved"])
        self.assertFalse(snapshot["vector_saved"])
        self.assertEqual("completed", workflow.process_memory_job("j1")["status"])
        workflow.extract_knowledge.assert_called_once()
        workflow.graph.merge_knowledge.assert_called_once()
        self.assertEqual(["j1", "j1"], [call.kwargs["point_id"] for call in workflow.save_memory.call_args_list])

    def test_lost_lease_cancels_before_provider_or_storage_side_effects(self):
        workflow, _ = outbox_workflow()
        workflow.memory_job_is_active.return_value = False
        self.assertEqual({"status": "cancelled"}, workflow.process_memory_job("j1"))
        workflow.extract_knowledge.assert_not_called()
        workflow.save_memory.assert_not_called()
        workflow.graph.merge_knowledge.assert_not_called()

    def test_duplicate_claim_does_not_execute_job_again(self):
        workflow, _ = outbox_workflow()
        workflow.claim_memory_job.return_value = None
        workflow.persistence.open.return_value.process_memory_job_job.return_value = None
        self.assertIsNone(workflow.process_memory_job("j1"))
        workflow.extract_knowledge.assert_not_called()
        workflow.save_memory.assert_not_called()

    def test_graph_write_crossing_deletion_tombstone_compensates_both_stores(self):
        workflow, _ = outbox_workflow()
        def delete_during_graph(*args, **kwargs):
            workflow.memory_job_is_active.return_value = False
            return {}
        workflow.graph.merge_knowledge.side_effect = delete_during_graph
        workflow.conversation_is_deleted = Mock(return_value=True)
        self.assertEqual("cancelled", workflow.process_memory_job("j1")["status"])
        workflow.vector.delete_memory_by_session.assert_called_once_with("s1")
        workflow.graph.remove_conversation_provenance.assert_called_once_with("s1", ["m1"])
