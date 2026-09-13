"""Migration adapters. LLM/memory algorithms remain unchanged until stages 5â€“6."""
from services import memory_service, llm_service
from app.infrastructure.vector.qdrant_vector_store import vector_store
from app.infrastructure.graph.neo4j_graph_store import graph_store
from services.ai_usage_service import set_usage_context as legacy_set_usage_context, reset_usage_context as legacy_reset_usage_context
from app.observability.correlation import correlation
from app.infrastructure.llm.composition import llm_workflows


class LegacyMemoryWorkflow:
    def __init__(self, uow=None):
        self.uow = uow

    def __getattr__(self, name):
        return getattr(memory_service, name)

    def cancel_memory_jobs_for_conversation(self, session_id):
        return memory_service.cancel_memory_jobs_for_conversation(session_id, self.uow.db)

    def get_session_history(self, session_id, limit=200):
        return memory_service.get_session_history(self.uow.db, session_id, limit=limit)

    def get_session_summary(self, session_id):
        return memory_service.get_session_summary(self.uow.db, session_id)


llm_gateway = llm_workflows


def set_usage_context(**values):
    correlation_token = correlation.set({**correlation.get(),
        "session_id": values.get("conversation_id"), "turn_id": values.get("turn_id")})
    return legacy_set_usage_context(**values), correlation_token


def reset_usage_context(token):
    usage_token, correlation_token = token
    try:
        legacy_reset_usage_context(usage_token)
    finally:
        correlation.reset(correlation_token)
