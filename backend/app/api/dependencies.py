"""Composition boundary; resolve concrete adapters outside application code."""
from fastapi.concurrency import run_in_threadpool
from configs.database import get_db, SessionLocal
from app.application.dependencies import ChatDependencies, ResourceDependencies
from app.infrastructure.persistence.unit_of_work import SQLAlchemyUnitOfWork
from app.infrastructure import application_wiring as bridges


def resource_dependencies(db=None):
    uow = SQLAlchemyUnitOfWork(db) if db is not None else None
    return ResourceDependencies(uow, bridges.graph_store, bridges.vector_store, bridges.bound_memory_workflows(uow))


def chat_dependencies(db=None):
    from app.api.errors import _internal_error_payload, _upstream_error_payload, _is_llm_provider_error
    uow = SQLAlchemyUnitOfWork(db) if db is not None else None
    memory = bridges.bound_memory_workflows(uow)
    return ChatDependencies(
        memory=memory, llm=bridges.llm_gateway, history=memory, uow=uow,
        threadpool=run_in_threadpool, prepare_session=_prepare_stream_session,
        internal_error_payload=_internal_error_payload,
        provider_error_payload=_upstream_error_payload, is_provider_error=_is_llm_provider_error,
        set_usage_context=bridges.set_usage_context, reset_usage_context=bridges.reset_usage_context,
    )


def _prepare_stream_session(request):
    from app.application.chat.prepare_session import prepare_stream_session
    return prepare_stream_session(request, chat_dependencies(SessionLocal()))
