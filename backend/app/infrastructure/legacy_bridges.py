"""Runtime dependency wiring; no imports from deprecated services."""
from app.infrastructure.vector.qdrant_vector_store import vector_store
from app.infrastructure.graph.neo4j_graph_store import graph_store
from app.observability.ai_telemetry import set_usage_context as legacy_set_usage_context, reset_usage_context as legacy_reset_usage_context
from app.observability.correlation import correlation
from app.infrastructure.llm.composition import llm_workflows
from app.infrastructure.memory.composition import memory_workflows
from app.infrastructure.memory.api_workflows import BoundMemoryWorkflows


def bound_memory_workflows(uow=None):
    return BoundMemoryWorkflows(memory_workflows, uow)


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
