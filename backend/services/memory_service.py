from app.domain.memory.contracts import TurnConflictError
import logging
import traceback
import time
import uuid
from contextvars import copy_context
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session
from schemas.chat_sch import MemoryContext, ProjectScopeContext, RetrievalStatus, QueryResolution
from models.message import Message
from models.conversation import Conversation
from models.memory_outbox import MemoryOutbox
from models.project import Project
from app.infrastructure.vector.qdrant_vector_store import vector_store

save_memory = vector_store.save_memory
reconcile_memory = vector_store.reconcile_memory
search_memory = vector_store.search_memory
search_project_memory_candidates = vector_store.search_project_memory_candidates
from app.infrastructure.graph.neo4j_graph_store import graph_store as neo4j_client
from services.llm_service import MemoryLLMUnavailableError, extract_knowledge, route_memory_query, _reference_matches
from services.ai_usage_service import usage_context
from configs.settings import settings
from services.diagnostic_service import (
    InternalFeatureError,
    current_exception_log,
    redact_diagnostic_log,
)

logger = logging.getLogger(__name__)

import re
import concurrent.futures


_MEMORY_RETRIEVAL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(2, min(int(settings.MEMORY_RETRIEVAL_WORKERS), 32)),
    thread_name_prefix="memory-retrieval",
)








_MEMORY_RECALL_RE = re.compile(
    r"\b(ingat|inget|pernah (?:aku|saya|gw|gue) (?:bilang|cerita)|"
    r"favoritku|kesukaanku|alergiku|ulang tahunku|lahirku|"
    r"siapa (?:pacar|teman|temen|ibu|ayah)ku|"
    r"(?:aku|saya|gw|gue) (?:kerja|tinggal|kuliah) (?:di )?(?:mana|dimana))\b"
)
_HISTORICAL_RE = re.compile(r"\b(dulu|pernah|sebelumnya|riwayat|kapan terakhir|waktu itu)\b")
_SEARCH_STOPWORDS = {
    "yang", "dan", "atau", "dari", "untuk", "dengan", "apa", "siapa", "kapan",
    "dimana", "mana", "apakah", "kamu", "masih", "ingat", "inget", "tentang", "aku",
    "saya", "gw", "gue", "nih", "dong", "deh", "kok", "ya", "itu", "ini", "pernah",
}

_VAGUE_PROJECT_REFERENCE_RE = re.compile(
    r"\b(?:project|proyek|projek)(?:\s*-?\s*(?:ku|saya|aku|gw|gue|milikku|ini|itu|tersebut))\b",
    flags=re.IGNORECASE,
)





















from models.llm_usage import LLMUsageLog

_MEMORY_RETRY_BASE_SECONDS = 30
_MEMORY_RETRY_MAX_SECONDS = 60 * 60
_MEMORY_JOB_LEASE_SECONDS = 5 * 60







































def process_conversation_summary(session_id: str) -> dict:
    """Fold old completed turns with an optimistic checkpoint; stale writers lose."""
    from configs.database import SessionLocal
    from services.llm_service import generate_session_summary

    db = SessionLocal()
    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .first()
        )
        if conversation is None:
            return {"status": "missing"}
        version = int(conversation.summary_version or 0)
        checkpoint = int(conversation.summary_through_sequence or 0)
        expected_next_sequence = int(conversation.next_turn_sequence or 1)
        current_summary = str(conversation.summary or "")
        rows = (
            db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.message_type == "normal",
                Message.turn_sequence.is_not(None),
                Message.turn_sequence > checkpoint,
            )
            .order_by(*Message.chronological_order())
            .all()
        )
    finally:
        db.close()

    if len(rows) <= 30:
        db = SessionLocal()
        try:
            db.query(Conversation).filter(
                Conversation.id == session_id,
                Conversation.summary_version == version,
                Conversation.next_turn_sequence == expected_next_sequence,
                Conversation.deleted_at.is_(None),
            ).update({Conversation.summary_pending: False}, synchronize_session=False)
            db.commit()
        finally:
            db.close()
        return {"status": "not_due", "folded": 0}

    keep_from_sequence = int(rows[-30].turn_sequence or 0)
    fold_candidates = [row for row in rows if int(row.turn_sequence or 0) < keep_from_sequence]
    if not fold_candidates:
        return {"status": "not_due", "folded": 0}
    fold_rows: list[Message] = []
    estimated_tokens = max(1, len(current_summary) // 3)
    for sequence in sorted({int(row.turn_sequence or 0) for row in fold_candidates}):
        group = [row for row in fold_candidates if int(row.turn_sequence or 0) == sequence]
        group_cost = sum(max(1, len(row.content or "") // 3) + 8 for row in group)
        if fold_rows and estimated_tokens + group_cost > 16_000:
            break
        fold_rows.extend(group)
        estimated_tokens += group_cost
    fold_through = max(int(row.turn_sequence or 0) for row in fold_rows)
    messages = [{"role": row.role, "content": row.content} for row in fold_rows]
    with usage_context(conversation_id=session_id, turn_id=None, job_id=None, job_attempt=None):
        updated_summary = generate_session_summary(current_summary, messages)

    db = SessionLocal()
    try:
        result = db.query(Conversation).filter(
            Conversation.id == session_id,
            Conversation.summary_version == version,
            Conversation.summary_through_sequence == checkpoint,
            Conversation.next_turn_sequence == expected_next_sequence,
            Conversation.deleted_at.is_(None),
        ).update(
            {
                Conversation.summary: updated_summary,
                Conversation.summary_version: version + 1,
                Conversation.summary_through_sequence: fold_through,
                Conversation.summary_pending: False,
            },
            synchronize_session=False,
        )
        db.commit()
        return {"status": "updated" if result == 1 else "stale", "folded": len(fold_rows)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def process_due_summaries(limit: int = 20) -> list[dict]:
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        ids = [
            row[0]
            for row in db.query(Conversation.id)
            .filter(Conversation.summary_pending.is_(True), Conversation.deleted_at.is_(None))
            .order_by(Conversation.updated_at.asc())
            .limit(min(max(int(limit), 1), 100))
            .all()
        ]
    finally:
        db.close()
    results = []
    for session_id in ids:
        try:
            results.append(process_conversation_summary(session_id))
        except Exception:
            logger.exception("Conversation summary retry failed for %s", session_id)
    return results


def record_internal_error(
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
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        user_row = db.get(Message, user_message_id) if user_message_id else None
        assistant_row = db.get(Message, assistant_message_id) if assistant_message_id else None
        if user_row is None and turn_id:
            user_row = db.query(Message).filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            ).first()
        if assistant_row is None and turn_id:
            assistant_row = db.query(Message).filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "assistant",
            ).first()
        created_count = 0

        # If persistence committed but failed before returning its identifiers,
        # reuse that just-written pair instead of creating duplicate messages.
        if user_row is None and assistant_row is None:
            recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
            recent_user = (
                db.query(Message)
                .filter(
                    Message.conversation_id == session_id,
                    Message.role == "user",
                    Message.message_type == "normal",
                    Message.content == user_message,
                    Message.created_at >= recent_cutoff,
                )
                .order_by(Message.created_at.desc())
                .first()
            )
            if recent_user is not None:
                recent_assistant = (
                    db.query(Message)
                    .filter(
                        Message.conversation_id == session_id,
                        Message.role == "assistant",
                        Message.message_type == "normal",
                        Message.created_at >= recent_user.created_at,
                    )
                    .order_by(Message.created_at.desc())
                    .first()
                )
                if recent_assistant is not None:
                    user_row = recent_user
                    assistant_row = recent_assistant

        if user_row is None:
            user_row = Message(
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
            assistant_row = Message(
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
            memory_job = db.get(MemoryOutbox, memory_job_id)
            if memory_job and memory_job.status != "completed":
                memory_job.status = "cancelled"
                memory_job.next_retry_at = None

        if created_count:
            conversation = db.get(Conversation, session_id)
            if conversation:
                conversation.message_count = int(conversation.message_count or 0) + created_count
                conversation.updated_at = datetime.now(timezone.utc)
        conversation = db.get(Conversation, session_id)
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


def _vector_reindex_snapshots(batch_size: int = 100):
    """Keyset scan: do not retain the entire archive or an open DB transaction."""
    from configs.database import SessionLocal
    cursor = ""
    while True:
        db = SessionLocal()
        try:
            jobs = (
                db.query(MemoryOutbox)
                .join(Conversation, Conversation.id == MemoryOutbox.conversation_id)
                .join(Message, Message.id == MemoryOutbox.user_message_id)
                .filter(
                    MemoryOutbox.id > cursor,
                    MemoryOutbox.status != "cancelled",
                    MemoryOutbox.extraction_completed.is_(True),
                    Conversation.deleted_at.is_(None),
                    Message.memory_status == "active",
                )
                .order_by(MemoryOutbox.id.asc())
                .limit(batch_size)
                .all()
            )
            snapshots = [
                {
                    "id": job.id, "conversation_id": job.conversation_id,
                    "message_id": job.user_message_id,
                    "extracted_knowledge": job.extracted_knowledge,
                    "stored_at": job.created_at.isoformat() if job.created_at else None,
                    "event_at": job.event_at.isoformat() if job.event_at else None,
                    "project_id": job.project_id,
                    "scope": job.scope or ("project" if job.project_id else "global"),
                } for job in jobs
            ]
        finally:
            db.close()
        if not snapshots:
            return
        cursor = snapshots[-1]["id"]
        yield from snapshots


def _vector_source_is_active(item: dict) -> bool:
    from configs.database import SessionLocal
    db = SessionLocal()
    try:
        return db.query(Conversation.id).join(
            Message, Message.conversation_id == Conversation.id
        ).filter(
            Conversation.id == item["conversation_id"],
            Conversation.deleted_at.is_(None),
            Message.id == item["message_id"],
            Message.memory_status == "active",
        ).first() is not None
    finally:
        db.close()


def reindex_vector_memory_from_outbox() -> dict:
    """Reconcile durable event projections, never infer completeness from count."""
    indexed = 0
    failures = 0
    eligible = 0
    skipped = 0
    for item in _vector_reindex_snapshots():
        eligible += 1
        try:
            if not _vector_source_is_active(item):
                skipped += 1
                continue
            assertion_text, assertion_spans = _vector_assertion_evidence(
                item.get("extracted_knowledge")
            )
            if not assertion_text:
                skipped += 1
                continue
            changed = reconcile_memory(
                assertion_text,
                {
                    "session_id": item["conversation_id"],
                    "message_id": item["message_id"],
                    "memory_job_id": item["id"],
                    "source_role": "user",
                    "epistemic_status": "user_assertion",
                    "assertion_spans": assertion_spans,
                    "modality": "asserted_fact",
                    "polarity": "positive",
                    "stored_at": item["stored_at"],
                    "event_at": item["event_at"],
                    "project_id": item["project_id"],
                    "scope": item["scope"],
                    "memory_status": "active",
                },
                point_id=item["id"],
            )
            if not _vector_source_is_active(item):
                set_memories_status = vector_store.set_memories_status
                set_memories_status([item["message_id"]], "inactive")
                skipped += 1
                continue
            indexed += int(changed)
            skipped += int(not changed)
        except Exception:
            failures += 1
            logger.exception("Could not reindex vector memory job %s", item["id"])
    return {"eligible": eligible, "indexed": indexed, "skipped": skipped, "failed": failures}

def generate_and_save_title(session_id: str, first_message: str):
    """
    Fungsi background task untuk men-generate judul sesi dan menyimpannya ke SQLite.
    """
    try:
        from configs.database import SessionLocal
        db = SessionLocal()
        try:
            from services.llm_service import generate_session_title
            with usage_context(conversation_id=session_id, turn_id=None, job_id=None, job_attempt=None):
                title = generate_session_title(first_message)
            
            conv = db.query(Conversation).filter(
                Conversation.id == session_id,
                Conversation.deleted_at.is_(None),
            ).first()
            if conv:
                conv.title = title
                db.commit()
                logger.info(f" -> Session title updated to: '{title}'")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in background task generate_and_save_title: {e}")

from app.infrastructure.memory.composition import create_memory_workflows
from app.compatibility import install_facade
memory_workflows = create_memory_workflows(_MEMORY_RETRIEVAL_EXECUTOR)
_vector_assertion_evidence = memory_workflows.assertion.vector_assertion_evidence


install_facade(__name__, {
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
    "_normalized_text": (memory_workflows.scope, "normalized_text"),
    "_mentions_project_name": (memory_workflows.scope, "mentions_project_name"),
    "_is_standalone_assistant_question": (memory_workflows.retrieval, "is_standalone_assistant_question"),
    "_memory_intent_keywords": (memory_workflows.retrieval, "memory_intent_keywords"),
    "_requires_personal_memory": (memory_workflows.retrieval, "requires_personal_memory"),
    "_local_search_keywords": (memory_workflows.retrieval, "local_search_keywords"),
    "_vector_assertion_evidence": (memory_workflows.assertion, "vector_assertion_evidence"),
    "_outbox_job_data": (memory_workflows.outbox, "outbox_job_data"),
    "save_memory": (memory_workflows, "save_memory"),
    "search_memory": (memory_workflows, "search_memory"),
    "search_project_memory_candidates": (memory_workflows, "search_project_memory_candidates"),
    "route_memory_query": (memory_workflows, "route_memory_query"),
    "extract_knowledge": (memory_workflows, "extract_knowledge"),
    "_submit_retrieval": (memory_workflows.retrieval_executor, "submit"),
    "neo4j_client": (memory_workflows, "graph"),
    "vector_store": (memory_workflows, "vector"),
})
