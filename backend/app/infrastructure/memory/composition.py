from configs.settings import settings
from app.application.memory.workflows import MemoryWorkflows
from app.domain.memory.scope_policy import ScopePolicy
from app.domain.memory.retrieval_policy import RetrievalPolicy
from app.domain.memory.assertion_policy import AssertionPolicy
from app.domain.memory.outbox_policy import OutboxPolicy
from app.infrastructure.persistence.memory.transaction import SQLAlchemyMemoryPersistence
from app.infrastructure.memory.retrieval_executor import RetrievalExecutor
from app.infrastructure.llm.composition import llm_workflows
from app.infrastructure.vector.qdrant_vector_store import vector_store
from app.infrastructure.graph.neo4j_graph_store import graph_store
from services.ai_usage_service import usage_context


def create_memory_workflows(executor=None):
    return MemoryWorkflows(config=settings, persistence=SQLAlchemyMemoryPersistence(settings),
        graph=graph_store, vector=vector_store, llm=llm_workflows,
        retrieval_executor=RetrievalExecutor(settings, executor), scope=ScopePolicy(settings),
        retrieval=RetrievalPolicy(settings), assertion=AssertionPolicy(settings),
        outbox=OutboxPolicy(settings), usage_context=usage_context)
