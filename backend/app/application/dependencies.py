from dataclasses import dataclass
from typing import Any, Callable

from app.ports.graph_store import GraphStore
from app.ports.llm_gateway import LLMGateway
from app.ports.memory_workflow import ConversationHistory, MemoryWorkflow
from app.ports.repositories import UnitOfWork
from app.ports.vector_store import VectorStore


@dataclass
class ResourceDependencies:
    uow: UnitOfWork | None
    graph: GraphStore
    vector: VectorStore
    memory: MemoryWorkflow


@dataclass
class ChatDependencies:
    memory: MemoryWorkflow
    llm: LLMGateway
    history: ConversationHistory | None
    uow: UnitOfWork | None
    threadpool: Callable[..., Any]
    prepare_session: Callable[..., Any]
    internal_error_payload: Callable[..., Any]
    provider_error_payload: Callable[..., dict]
    is_provider_error: Callable[[Exception], bool]
    set_usage_context: Callable[..., Any]
    reset_usage_context: Callable[..., Any]
