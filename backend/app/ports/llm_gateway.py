from collections.abc import AsyncIterator
from typing import Any, Protocol


class LLMGateway(Protocol):
    DEFAULT_MODEL_NAME: str
    def generate_chat_response_stream(self, user_message: str, *args: Any, **kwargs: Any) -> AsyncIterator[dict]: ...
    async def analyze_internal_error(self, **kwargs: Any) -> str: ...
