"""Forwarding facade only; remove after consumer/patch migration in stage 8."""
import logging
import time
import uuid
import concurrent.futures
from datetime import datetime, timedelta, timezone
from app.domain.memory.contracts import TurnConflictError
from app.domain.llm.contracts import MemoryLLMUnavailableError, ERROR_FALLBACK_MSG


from app.infrastructure.memory.composition import memory_workflows
from app.compatibility import install_facade


install_facade(__name__, {
    "settings": (memory_workflows, "config"),
    "_MEMORY_RETRIEVAL_EXECUTOR": (memory_workflows.retrieval_executor, "executor"),
    "_resolve_project_scope": (memory_workflows, "resolve_project_scope"),
    "retrieve_context": (memory_workflows, "retrieve_context"),
    "_filter_active_vector_memories": (memory_workflows, "filter_active_vector_memories"),
    "get_session_history": (memory_workflows, "get_session_history"),
    "get_session_summary": (memory_workflows, "get_session_summary"),
    "begin_turn": (memory_workflows, "begin_turn"),
    "mark_turn_status": (memory_workflows, "mark_turn_status"),
    "save_interaction": (memory_workflows, "save_interaction"),
    "_get_memory_job_snapshot": (memory_workflows, "get_memory_job_snapshot"),
    "_update_memory_job": (memory_workflows, "update_memory_job"),
    "_memory_job_is_active": (memory_workflows, "memory_job_is_active"),
    "_conversation_is_deleted": (memory_workflows, "conversation_is_deleted"),
    "_leased_memory_job_snapshot": (memory_workflows, "leased_memory_job_snapshot"),
    "_claim_memory_job": (memory_workflows, "claim_memory_job"),
    "_finish_memory_job": (memory_workflows, "finish_memory_job"),
    "_cancel_claim": (memory_workflows, "cancel_claim"),
    "process_memory_job": (memory_workflows, "process_memory_job"),
    "_compensate_deleted_conversation": (memory_workflows, "compensate_deleted_conversation"),
    "set_source_messages_memory_status": (memory_workflows, "set_source_messages_memory_status"),
    "process_due_memory_jobs": (memory_workflows, "process_due_memory_jobs"),
    "list_memory_jobs": (memory_workflows, "list_memory_jobs"),
    "retry_memory_job": (memory_workflows, "retry_memory_job"),
    "cancel_memory_jobs_for_conversation": (memory_workflows, "cancel_memory_jobs_for_conversation"),
    "process_conversation_summary": (memory_workflows, "process_conversation_summary"),
    "process_due_summaries": (memory_workflows, "process_due_summaries"),
    "record_internal_error": (memory_workflows, "record_internal_error"),
    "_vector_reindex_snapshots": (memory_workflows, "vector_reindex_snapshots"),
    "_vector_source_is_active": (memory_workflows, "vector_source_is_active"),
    "reindex_vector_memory_from_outbox": (memory_workflows, "reindex_vector_memory_from_outbox"),
    "generate_and_save_title": (memory_workflows, "generate_and_save_title"),
    "_normalized_text": (memory_workflows.scope, "normalized_text"),
    "_mentions_project_name": (memory_workflows.scope, "mentions_project_name"),
    "_is_standalone_assistant_question": (memory_workflows.retrieval, "is_standalone_assistant_question"),
    "_memory_intent_keywords": (memory_workflows.retrieval, "memory_intent_keywords"),
    "_requires_personal_memory": (memory_workflows.retrieval, "requires_personal_memory"),
    "_local_search_keywords": (memory_workflows.retrieval, "local_search_keywords"),
    "_vector_assertion_evidence": (memory_workflows.assertion, "vector_assertion_evidence"),
    "_outbox_job_data": (memory_workflows.outbox, "outbox_job_data"),
    "save_memory": (memory_workflows, "save_memory"),
    "reconcile_memory": (memory_workflows, "reconcile_memory"),
    "search_memory": (memory_workflows, "search_memory"),
    "search_project_memory_candidates": (memory_workflows, "search_project_memory_candidates"),
    "route_memory_query": (memory_workflows, "route_memory_query"),
    "extract_knowledge": (memory_workflows, "extract_knowledge"),
    "_submit_retrieval": (memory_workflows.retrieval_executor, "submit"),
    "neo4j_client": (memory_workflows, "graph"),
    "vector_store": (memory_workflows, "vector"),
})
