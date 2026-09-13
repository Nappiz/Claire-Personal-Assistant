from unittest import TestCase
from test_memory_read_boundaries import fake_memory


class MemoryTurnBoundaryTests(TestCase):
    def test_missing_begin_turn_rolls_back_and_closes_without_provider_io(self):
        workflow = fake_memory()
        transaction = workflow.persistence.open.return_value
        transaction.begin_turn_conversation.return_value = None
        with self.assertRaisesRegex(ValueError, "Session not found"):
            workflow.begin_turn("missing", "halo", "turn1")
        transaction.rollback.assert_called_once()
        transaction.close.assert_called_once()
        workflow.llm.extract_knowledge.assert_not_called()

    def test_invalid_status_is_rejected_before_opening_transaction(self):
        workflow = fake_memory()
        with self.assertRaisesRegex(ValueError, "Unsupported turn status"):
            workflow.mark_turn_status("s1", "t1", "unknown")
        workflow.persistence.open.assert_not_called()

    def test_failed_interaction_never_starts_external_memory_pipeline(self):
        workflow = fake_memory()
        transaction = workflow.persistence.open.return_value
        transaction.save_interaction_conversation.return_value = None
        with self.assertRaisesRegex(ValueError, "Session was deleted"):
            workflow.save_interaction("s1", "halo", "jawaban", {})
        transaction.rollback.assert_called_once()
        transaction.close.assert_called_once()
        workflow.vector.save_memory.assert_not_called()
        workflow.graph.merge_knowledge.assert_not_called()
