"""Compatibility facade. Remove after stages 5Ã¢â‚¬â€œ8 migrate legacy consumers."""
from app.compatibility import install_facade
from app.api.router import router
from app.api import dependencies, errors, sse
from app.api.routers import chat, conversations, projects, graph, memory, system
from app.infrastructure import legacy_bridges as bridges
from services import qdrant_service, memory_service, llm_service
install_facade(__name__, {
    "get_projects": (projects, "get_projects"),
    "create_project": (projects, "create_project"),
    "update_project": (projects, "update_project"),
    "delete_project": (projects, "delete_project"),
    "get_sessions": (conversations, "get_sessions"),
    "set_session_pin": (conversations, "set_session_pin"),
    "get_history": (conversations, "get_history"),
    "delete_session": (conversations, "delete_session"),
    "get_knowledge_graph": (graph, "get_knowledge_graph"),
    "delete_graph_node": (graph, "delete_graph_node"),
    "update_graph_node": (graph, "update_graph_node"),
    "delete_graph_fact": (graph, "delete_graph_fact"),
    "update_graph_fact": (graph, "update_graph_fact"),
    "get_memory_jobs": (memory, "get_memory_jobs"),
    "retry_memory_job": (memory, "retry_memory_job"),
    "get_system_stats": (system, "get_system_stats"),
    "chat_endpoint": (chat, "chat_endpoint"),
    "stream_chat_endpoint": (chat, "stream_chat_endpoint"),
    "_prepare_stream_session": (dependencies, "_prepare_stream_session"),
    "SessionLocal": (dependencies, "SessionLocal"),
    "neo4j_client": (bridges, "graph_store"),
    "get_qdrant_stats": (qdrant_service, "get_stats"),
    "delete_memory_by_session": (qdrant_service, "delete_memory_by_session"),
    "_sse_data": (sse, "_sse_data"),
    "_upstream_error_payload": (errors, "_upstream_error_payload"),
    "_is_llm_provider_error": (errors, "_is_llm_provider_error"),
    "_internal_error_payload": (errors, "_internal_error_payload"),
})
