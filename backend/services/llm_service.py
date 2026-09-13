"""Compatibility facade. Single owners in domain/application/LLM adapters.
Remove after legacy import/patch consumers migrate, by roadmap stage 8.
"""
import asyncio
import json
import logging
import re
import time
from openai import AsyncOpenAI, OpenAI
from configs.database import SessionLocal
from configs.settings import settings
from app.domain.llm.contracts import DEFAULT_MODEL_NAME, ERROR_FALLBACK_MSG, MemoryLLMUnavailableError, MemoryRouteDecision
from app.domain.llm.contracts import CONTEXT_REFERENCE_RE as _CONTEXT_REFERENCE_RE
from app.domain.llm.tool_contracts import WEB_TOOL_DEFINITIONS as _WEB_TOOL_DEFINITIONS, WEB_TOOL_INSTRUCTIONS as _WEB_TOOL_INSTRUCTIONS
from app.domain.graph.fact_policy import validate_extracted_knowledge, get_relation_policy, RELATION_POLICIES
from app.infrastructure.llm import client_factory
from app.infrastructure.llm.composition import llm_workflows, gateway, prompts, references, extraction, responses, tools
from app.compatibility import install_facade

install_facade(__name__, {
    "_estimate_prompt_tokens": (prompts, "estimate_prompt_tokens"),
    "_bounded_memory_items": (prompts, "bounded_memory_items"),
    "_fit_history_to_prompt_budget": (prompts, "fit_history_to_prompt_budget"),
    "_resolve_timezone": (prompts, "resolve_timezone"),
    "_current_temporal_context": (prompts, "current_temporal_context"),
    "_temporal_prompt_section": (prompts, "temporal_prompt_section"),
    "_safe_context_json": (prompts, "safe_context_json"),
    "_build_chat_messages": (prompts, "build_chat_messages"),
    "_bounded_web_recovery_payload": (prompts, "bounded_web_recovery_payload"),
    "_build_final_recovery_messages": (prompts, "build_final_recovery_messages"),
    "_reference_context": (references, "reference_context"),
    "_reference_matches": (references, "reference_matches"),
    "_inline_person_reference": (references, "inline_person_reference"),
    "_reference_clarification": (references, "reference_clarification"),
    "_contains_explicit_personal_assertion": (extraction, "contains_explicit_personal_assertion"),
    "_has_statement_in_question_turn": (extraction, "has_statement_in_question_turn"),
    "_is_memory_recall_question": (extraction, "is_memory_recall_question"),
    "_sanitize_extracted_knowledge": (extraction, "sanitize_extracted_knowledge"),
    "_validate_extraction_envelope": (extraction, "validate_extraction_envelope"),
    "_format_extraction_history": (extraction, "format_extraction_history"),
    "_usage_values": (responses, "usage_values"),
    "_add_usage": (responses, "add_usage"),
    "_finish_reason_text": (responses, "finish_reason_text"),
    "_stream_delta_text": (responses, "stream_delta_text"),
    "_record_stream_diagnostics": (responses, "record_stream_diagnostics"),
    "_completion_outcome": (responses, "completion_outcome"),
    "_tool_arguments": (tools, "tool_arguments"),
    "_web_search_plan_from_call": (tools, "web_search_plan_from_call"),
    "_web_tools_allowed_for_turn": (tools, "web_tools_allowed_for_turn"),
    "get_llm_client": (gateway, "get_llm_client"),
    "_memory_llm_candidates": (gateway, "memory_llm_candidates"),
    "_memory_completion": (gateway, "memory_completion"),
    "tracked_sync_completion": (gateway, "tracked_sync_completion"),
    "tracked_async_completion": (gateway, "tracked_async_completion"),
    "_serialized_tool_calls": (gateway, "serialized_tool_calls"),
    "_serialized_assistant_tool_message": (gateway, "serialized_assistant_tool_message"),
    "generate_chat_response": (llm_workflows, "generate_chat_response"),
    "generate_chat_response_stream": (llm_workflows, "generate_chat_response_stream"),
    "extract_knowledge": (llm_workflows, "extract_knowledge"),
    "route_memory_query": (llm_workflows, "route_memory_query"),
    "generate_search_queries": (llm_workflows, "generate_search_queries"),
    "generate_session_title": (llm_workflows, "generate_session_title"),
    "generate_session_summary": (llm_workflows, "generate_session_summary"),
    "analyze_internal_error": (llm_workflows, "analyze_internal_error"),
    "_get_llm_connection": (client_factory, "get_llm_connection"),
    "_create_async_llm_client": (client_factory, "create_async_llm_client"),
    "get_async_llm_client": (client_factory, "get_async_llm_client"),
    "OpenAI": (client_factory, "OpenAI"),
    "AsyncOpenAI": (client_factory, "AsyncOpenAI"),
    "SessionLocal": (client_factory, "SessionLocal"),
})
