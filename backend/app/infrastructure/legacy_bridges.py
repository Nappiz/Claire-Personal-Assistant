"""Migration adapters. LLM/memory algorithms remain unchanged until stages 5â€“6."""
from services import memory_service, llm_service, qdrant_service
from services.neo4j_service import neo4j_client
from services.ai_usage_service import set_usage_context as legacy_set_usage_context, reset_usage_context as legacy_reset_usage_context
from app.observability.correlation import correlation


class LegacyLLMGateway:
    @property
    def DEFAULT_MODEL_NAME(self):
        return llm_service.DEFAULT_MODEL_NAME

    def generate_chat_response_stream(self, *args, **kwargs):
        return llm_service.generate_chat_response_stream(*args, **kwargs)

    async def analyze_internal_error(self, **kwargs):
        return await llm_service.analyze_internal_error(**kwargs)


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


class LegacyVectorStore:
    def __getattr__(self, name):
        return getattr(qdrant_service, name)


llm_gateway = LegacyLLMGateway()
vector_store = LegacyVectorStore()
graph_store = neo4j_client


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
