from __future__ import annotations
import logging
import traceback
import time
import uuid
import re
import concurrent.futures
from datetime import datetime, timedelta, timezone
from typing import Any
from schemas.chat_sch import MemoryContext, ProjectScopeContext, RetrievalStatus, QueryResolution
from app.domain.llm.contracts import MemoryLLMUnavailableError, ERROR_FALLBACK_MSG
from app.domain.memory.contracts import TurnConflictError, _MEMORY_RECALL_RE, _HISTORICAL_RE, _SEARCH_STOPWORDS, _VAGUE_PROJECT_REFERENCE_RE, _MEMORY_RETRY_BASE_SECONDS, _MEMORY_RETRY_MAX_SECONDS, _MEMORY_JOB_LEASE_SECONDS
from app.domain.diagnostics import InternalFeatureError, current_exception_log, redact_diagnostic_log
logger = logging.getLogger("services.memory_service")

class RecordInternalError:
    def record_internal_error(self, 
        *,
        session_id: str,
        user_message: str,
        analysis: str,
        error_details: dict,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
        memory_job_id: str | None = None,
        turn_id: str | None = None,
        turn_sequence: int | None = None,
    ) -> None:
        """Persist an error turn and keep it out of Claire's conversational memory."""
    
        db = self.persistence.open()
        try:
            user_row = db.record_internal_error_user_row(user_message_id) if user_message_id else None
            assistant_row = db.record_internal_error_assistant_row(assistant_message_id) if assistant_message_id else None
            if user_row is None and turn_id:
                user_row = db.record_internal_error_user_row_after_claim(session_id, turn_id)
            if assistant_row is None and turn_id:
                assistant_row = db.record_internal_error_assistant_row_after_claim(session_id, turn_id)
            created_count = 0
    
            # If persistence committed but failed before returning its identifiers,
            # reuse that just-written pair instead of creating duplicate messages.
            if user_row is None and assistant_row is None:
                recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
                recent_user = (
                    db.record_internal_error_recent_user(recent_cutoff, session_id, user_message)
                )
                if recent_user is not None:
                    recent_assistant = (
                        db.record_internal_error_recent_assistant(recent_user, session_id)
                    )
                    if recent_assistant is not None:
                        user_row = recent_user
                        assistant_row = recent_assistant
    
            if user_row is None:
                user_row = db.new_message(
                    conversation_id=session_id,
                    role="user",
                    content=user_message,
                    message_type="failed_turn",
                    turn_id=turn_id,
                    turn_sequence=turn_sequence,
                )
                db.add(user_row)
                created_count += 1
            else:
                user_row.message_type = "failed_turn"
    
            if assistant_row is None:
                assistant_row = db.new_message(
                    conversation_id=session_id,
                    role="assistant",
                    content=analysis,
                    message_type="internal_error",
                    error_details=error_details,
                    turn_id=turn_id,
                    turn_sequence=turn_sequence,
                )
                db.add(assistant_row)
                created_count += 1
            else:
                assistant_row.content = analysis
                assistant_row.message_type = "internal_error"
                assistant_row.error_details = error_details
            if user_row.created_at and assistant_row.created_at:
                user_created_at = user_row.created_at
                assistant_created_at = assistant_row.created_at
                if user_created_at.tzinfo is None:
                    user_created_at = user_created_at.replace(tzinfo=timezone.utc)
                if assistant_created_at.tzinfo is None:
                    assistant_created_at = assistant_created_at.replace(tzinfo=timezone.utc)
                if assistant_created_at <= user_created_at:
                    assistant_row.created_at = user_created_at + timedelta(microseconds=1)
    
            if memory_job_id:
                memory_job = db.record_internal_error_memory_job(memory_job_id)
                if memory_job and memory_job.status != "completed":
                    memory_job.status = "cancelled"
                    memory_job.next_retry_at = None
    
            if created_count:
                conversation = db.record_internal_error_conversation_after_claim(session_id)
                if conversation:
                    conversation.message_count = int(conversation.message_count or 0) + created_count
                    conversation.updated_at = datetime.now(timezone.utc)
            conversation = db.record_internal_error_conversation_after_claim(session_id)
            if conversation and turn_id and conversation.active_turn_id == turn_id:
                conversation.active_turn_id = None
                conversation.active_turn_expires_at = None
    
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist internal error turn for session %s", session_id)
            raise
        finally:
            db.close()
