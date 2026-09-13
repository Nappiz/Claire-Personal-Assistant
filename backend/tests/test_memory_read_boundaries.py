import concurrent.futures
from contextlib import nullcontext
from types import SimpleNamespace as Record
from unittest import TestCase
from unittest.mock import Mock

from app.application.memory.workflows import MemoryWorkflows
from app.domain.memory.scope_policy import ScopePolicy
from app.domain.memory.retrieval_policy import RetrievalPolicy
from app.domain.memory.assertion_policy import AssertionPolicy
from app.domain.memory.outbox_policy import OutboxPolicy
from app.domain.llm.memory_query_policy import MemoryQueryPolicy
from app.domain.llm.contracts import MemoryRouteDecision


class ImmediateExecutor:
    def submit(self, function, *args, **kwargs):
        future = concurrent.futures.Future()
        try: future.set_result(function(*args, **kwargs))
        except BaseException as error: future.set_exception(error)
        return future


def fake_memory(**overrides):
    config = Record(MEMORY_RETRIEVAL_TIMEOUT_SECONDS=1, MEMORY_SEARCH_SCORE_THRESHOLD=0.75,
                    MEMORY_FACT_CONFIDENCE_THRESHOLD=0.7)
    transaction = Mock()
    transaction.resolve_project_scope_projects.return_value = [Record(id="p1", name="Atlas")]
    transaction.filter_active_vector_memories_active_ids.return_value = [("m1",)]
    persistence = Mock()
    persistence.open.return_value = transaction
    persistence.wrap.side_effect = lambda db: db
    llm = Mock()
    llm.references = MemoryQueryPolicy(config)
    llm.route_memory_query.return_value = MemoryRouteDecision("needed", ["nafiz"])
    vector, graph = Mock(), Mock()
    vector.search_memory.return_value = [{"content": "nafiz works at Acme", "score": 0.9, "message_id": "m1"}]
    graph.search_knowledge.return_value = ["nafiz WORKS_AT Acme"]
    values = dict(config=config, persistence=persistence, llm=llm, vector=vector, graph=graph,
                  retrieval_executor=ImmediateExecutor(), scope=ScopePolicy(config),
                  retrieval=RetrievalPolicy(config), assertion=AssertionPolicy(config),
                  outbox=OutboxPolicy(config), usage_context=lambda **kwargs: nullcontext())
    values.update(overrides)
    return MemoryWorkflows(**values)


class MemoryReadBoundaryTests(TestCase):
    def test_scope_and_retrieval_use_only_injected_ports(self):
        workflow = fake_memory()
        context = workflow.retrieve_context("aku kerja di mana?", project_id="p1")
        self.assertEqual("p1", context.project_scope.project_id)
        self.assertEqual("nafiz works at Acme", context.qdrant_context[0].content)
        workflow.vector.search_memory.assert_called_once_with("aku kerja di mana?", 3, project_id="p1")
        workflow.graph.search_knowledge.assert_called_once()

    def test_storage_failure_retains_other_backend_and_degraded_status(self):
        workflow = fake_memory()
        workflow.search_memory.side_effect = RuntimeError("vector offline")
        context = workflow.retrieve_context("aku kerja di mana?")
        self.assertEqual([], context.qdrant_context)
        self.assertEqual(["nafiz WORKS_AT Acme"], context.neo4j_context)
        self.assertTrue(context.retrieval_status.degraded)
        self.assertIn("semantic_memory_unavailable", context.retrieval_status.warnings)

    def test_assistant_identity_short_circuits_all_external_ports(self):
        workflow = fake_memory()
        context = workflow.retrieve_context("siapa yang nyiptain kamu?")
        self.assertEqual([], context.neo4j_context)
        workflow.persistence.open.assert_not_called()
        workflow.llm.route_memory_query.assert_not_called()
