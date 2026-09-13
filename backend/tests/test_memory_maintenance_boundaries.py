from types import SimpleNamespace as Record
from unittest import TestCase
from unittest.mock import Mock

from test_memory_read_boundaries import fake_memory


class MemoryMaintenanceBoundaryTests(TestCase):
    def test_summary_not_due_closes_read_and_checkpoint_transactions(self):
        workflow = fake_memory()
        transaction = workflow.persistence.open.return_value
        transaction.process_conversation_summary_conversation.return_value = Record(
            summary_version=2, summary_through_sequence=1, next_turn_sequence=3, summary="lama")
        transaction.process_conversation_summary_rows.return_value = []
        self.assertEqual({"status": "not_due", "folded": 0}, workflow.process_conversation_summary("s1"))
        self.assertEqual(2, transaction.close.call_count)
        transaction.process_conversation_summary_update.assert_called_once_with(3, "s1", 2)
        workflow.llm.generate_session_summary.assert_not_called()

    def test_summary_compare_and_swap_rejects_stale_writer_with_fake_repository(self):
        workflow = fake_memory()
        transaction = workflow.persistence.open.return_value
        transaction.process_conversation_summary_conversation.return_value = Record(
            summary_version=2, summary_through_sequence=0, next_turn_sequence=18, summary="lama")
        transaction.process_conversation_summary_rows.return_value = [
            Record(turn_sequence=sequence, role=role, content=f"{sequence}-{role}")
            for sequence in range(1, 18) for role in ("user", "assistant")]
        transaction.process_conversation_summary_result.return_value = 0
        workflow.llm.generate_session_summary.return_value = "baru"
        result = workflow.process_conversation_summary("s1")
        self.assertEqual("stale", result["status"])
        self.assertEqual(4, result["folded"])
        self.assertEqual(["user", "assistant", "user", "assistant"],
                         [message["role"] for message in workflow.llm.generate_session_summary.call_args.args[1]])

    def test_title_generation_and_save_use_injected_ports(self):
        workflow = fake_memory()
        conversation = Record(title="lama")
        transaction = workflow.persistence.open.return_value
        transaction.generate_and_save_title_conv.return_value = conversation
        workflow.llm.generate_session_title.return_value = "baru"
        workflow.generate_and_save_title("s1", "halo")
        self.assertEqual("baru", conversation.title)
        transaction.commit.assert_called_once()
        transaction.close.assert_called_once()

    def test_reindex_preserves_late_deletion_compensation_call_shape(self):
        workflow = fake_memory()
        workflow.vector_reindex_snapshots = Mock(return_value=[dict(
            id="j1", conversation_id="s1", message_id="m1", project_id=None,
            scope="global", stored_at=None, event_at=None, extracted_knowledge={
                "nodes": [{"id": "p", "name": "nafiz"}, {"id": "o", "name": "Acme"}],
                "edges": [{"source": "p", "target": "o", "relation": "WORKS_AT"}]})])
        workflow.vector_source_is_active = Mock(side_effect=[True, False])
        workflow.reconcile_memory.return_value = True
        result = workflow.reindex_vector_memory_from_outbox()
        self.assertEqual({"eligible": 1, "indexed": 0, "skipped": 1, "failed": 0}, result)
        workflow.vector.set_memories_status.assert_called_once_with(["m1"], "inactive")
