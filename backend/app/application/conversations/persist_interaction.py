from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta, timezone
from app.domain.llm.contracts import ERROR_FALLBACK_MSG
from app.domain.memory.contracts import TurnConflictError
logger = logging.getLogger("services.memory_service")

class PersistInteraction:
    def save_interaction(self, 
        session_id: str,
        user_message: str,
        ai_response: str,
        usage: dict,
        context=None,
        session_history: list | None = None,
        session_summary: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        report_errors: bool = False,
        project_id: str | None = None,
        project_name: str | None = None,
        turn_id: str | None = None,
        turn_sequence: int | None = None,
        user_message_id: str | None = None,
        process_memory: bool = True,
        response_status: str = "complete",
        finish_reason: str | None = None,
    ):
        """Commit a completed turn and its outbox atomically; external memory runs later."""
        response_status, finish_reason = self.turn.normalize_completion(usage, response_status, finish_reason)
    
        db = self.persistence.open()
        assistant_message_id: str | None = None
        memory_job_id: str | None = None
        try:
            conversation = (
                db.save_interaction_conversation(session_id)
            )
            if conversation is None:
                raise ValueError("Session was deleted before the turn could be committed")
    
            msg_user = db.save_interaction_msg_user(user_message_id) if user_message_id else None
            if turn_id and msg_user is None:
                msg_user = (
                    db.save_interaction_msg_user_after_claim(session_id, turn_id)
                )
            created_user = False
            if msg_user is None:
                sequence = int(turn_sequence or conversation.next_turn_sequence or 1)
                msg_user = db.new_message(
                    conversation_id=session_id,
                    role="user",
                    content=user_message,
                    message_type="normal",
                    turn_id=turn_id,
                    turn_sequence=sequence,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(msg_user)
                db.flush()
                created_user = True
                conversation.next_turn_sequence = max(int(conversation.next_turn_sequence or 1), sequence + 1)
            elif msg_user.content != user_message:
                raise TurnConflictError("Persisted turn content does not match this request")
            else:
                sequence = int(msg_user.turn_sequence or turn_sequence or conversation.next_turn_sequence or 1)
                msg_user.message_type = "normal"
                msg_user.error_details = None
                msg_user.turn_sequence = sequence
    
            msg_ai = None
            if turn_id:
                msg_ai = (
                    db.save_interaction_msg_ai(session_id, turn_id)
                )
            created_assistant = False
            if msg_ai is None:
                assistant_created_at = datetime.now(timezone.utc)
                user_created_at = msg_user.created_at
                if user_created_at and user_created_at.tzinfo is None:
                    user_created_at = user_created_at.replace(tzinfo=timezone.utc)
                if user_created_at and assistant_created_at <= user_created_at:
                    assistant_created_at = user_created_at + timedelta(microseconds=1)
                msg_ai = db.new_message(
                    conversation_id=session_id,
                    role="assistant",
                    content=ai_response,
                    message_type="normal",
                    turn_id=turn_id,
                    turn_sequence=sequence,
                    created_at=assistant_created_at,
                    response_status=response_status,
                    finish_reason=finish_reason,
                )
                db.add(msg_ai)
                db.flush()
                created_assistant = True
            elif msg_ai.content != ai_response:
                raise TurnConflictError("A different assistant result is already committed for this turn")
            assistant_message_id = str(msg_ai.id)
            user_message_id = str(msg_user.id)
    
            conversation.message_count = int(conversation.message_count or 0) + int(created_user) + int(created_assistant)
            conversation.summary_pending = int(conversation.message_count or 0) > 30
            if not turn_id or conversation.active_turn_id == turn_id:
                conversation.active_turn_id = None
                conversation.active_turn_expires_at = None
            conversation.updated_at = datetime.now(timezone.utc)
    
            if usage and usage.get("total_tokens", 0) > 0 and created_assistant and not usage.get("invocation_ids"):
                db.add(
                    db.new_usage(
                        provider=llm_provider or "unknown",
                        model=llm_model or "unknown",
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_cost=None,
                        conversation_id=session_id,
                    )
                )
    
            if ai_response != ERROR_FALLBACK_MSG:
                memory_job = db.save_interaction_memory_job(turn_id) if turn_id else None
                if memory_job is None:
                    neo4j_ctx = context.neo4j_context if context and hasattr(context, "neo4j_context") else []
                    memory_job = db.new_outbox(
                        id=turn_id or str(uuid.uuid4()),
                        conversation_id=session_id,
                        user_message_id=user_message_id,
                        user_message=user_message,
                        assistant_response=ai_response,
                        session_history=(
                            ([{"role": "summary", "content": session_summary}] if session_summary else [])
                            + list((session_history or [])[-12:])
                        ),
                        neo4j_context=list(neo4j_ctx or []),
                        project_id=project_id,
                        project_name=project_name,
                        scope="project" if project_id else "global",
                        status="pending",
                        event_at=msg_user.created_at or datetime.now(timezone.utc),
                    )
                    db.add(memory_job)
                    db.flush()
                memory_job_id = str(memory_job.id)
    
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist chat interaction and memory outbox")
            raise
        finally:
            db.close()
    
        job_result = None
        if memory_job_id and process_memory:
            job_result = self.process_memory_job(memory_job_id, report_errors=report_errors)
        return {
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "memory_job_id": memory_job_id,
            "memory_job": job_result,
            "summary_pending": True,
        }
