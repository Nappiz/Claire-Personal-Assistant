from app.infrastructure.llm import client_factory
from app.infrastructure.llm.memory_completion import MemoryCompletion
from app.infrastructure.llm.provider_serializers import ProviderSerializers
from app.infrastructure.llm.response_normalizer import normalize_response, NormalizedStream
from services import ai_usage_service


class OpenAICompletionGateway(MemoryCompletion, ProviderSerializers):
    def __init__(self, config):
        self.config = config

    def get_llm_client(self, *args, **kwargs):
        return client_factory.get_llm_client(*args, **kwargs)

    def get_llm_connection(self, *args, **kwargs):
        return client_factory.get_llm_connection(*args, **kwargs)

    def create_async_llm_client(self, *args, **kwargs):
        return client_factory.create_async_llm_client(*args, **kwargs)

    def get_async_llm_client(self, *args, **kwargs):
        return client_factory.get_async_llm_client(*args, **kwargs)

    def tracked_sync_completion(self, client, **kwargs):
        response, invocation_id = ai_usage_service.tracked_sync_completion(client, **kwargs)
        return normalize_response(response), invocation_id

    async def tracked_async_completion(self, client, **kwargs):
        response, invocation_id = await ai_usage_service.tracked_async_completion(client, **kwargs)
        return (NormalizedStream(response) if kwargs.get("stream") else normalize_response(response)), invocation_id
