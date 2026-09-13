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














def _vector_assertion_evidence(extracted: dict | None) -> tuple[str, list[dict]]:
    """Render only validated positive assertions for semantic memory.

    SQLite retains the raw conversation. Qdrant receives compact, resolved graph
    evidence so questions, quotations, hypotheticals, and elliptical chatter are
    not mislabeled as factual assertions merely because the user authored them.
    """
    data = extracted if isinstance(extracted, dict) else {}
    nodes = {
        str(node.get("id")): node
        for node in data.get("nodes", [])
        if isinstance(node, dict) and node.get("id") and node.get("name")
    }
    spans: list[dict] = []
    rendered: list[str] = []
    seen: set[str] = set()
    evidence_offset = 0
    for edge in data.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if float(edge.get("confidence", 1.0) or 0.0) < settings.MEMORY_FACT_CONFIDENCE_THRESHOLD:
            continue
        relation = " ".join(str(edge.get("relation") or "").replace("_", " ").split()).lower()
        if not relation or relation == "belongs to":
            continue
        source = nodes.get(str(edge.get("source")))
        target = nodes.get(str(edge.get("target")))
        if not source or not target:
            continue
        if min(float(source.get("confidence", 1.0)), float(target.get("confidence", 1.0))) < settings.MEMORY_FACT_CONFIDENCE_THRESHOLD:
            continue
        def resolved_name(node: dict) -> str:
            name = str(node["name"])
            context = str(node.get("identity_context") or "").strip()
            if str(node.get("label") or "").lower() == "person" and context:
                return f"{name} ({context})"
            return name
        assertion = " ".join(f"{resolved_name(source)} {relation} {resolved_name(target)}".split())
        fingerprint = assertion.casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rendered.append(assertion)
        spans.append({
            "text": assertion,
            "modality": "asserted_fact",
            "polarity": "positive",
            "source_ref": str(edge.get("source")),
            "target_ref": str(edge.get("target")),
            "relation": str(edge.get("relation") or "").upper(),
            "span_start": evidence_offset,
            "span_end": evidence_offset + len(assertion),
        })
        evidence_offset += len(assertion) + 2
    return ". ".join(rendered), spans


def set_source_messages_memory_status(message_ids: list[str], status: str) -> int:
    if status not in {"active", "inactive"}:
        raise ValueError("Unsupported memory status")
    clean_ids = {str(item) for item in message_ids if item}
    if not clean_ids:
        return 0
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        count = db.query(Message).filter(Message.id.in_(clean_ids)).update(
            {Message.memory_status: status}, synchronize_session=False
        )
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()





from models.llm_usage import LLMUsageLog

_MEMORY_RETRY_BASE_SECONDS = 30
_MEMORY_RETRY_MAX_SECONDS = 60 * 60
_MEMORY_JOB_LEASE_SECONDS = 5 * 60


def _outbox_job_data(job: MemoryOutbox) -> dict:
    """Return only operational metadata; never expose chat payload by default."""
    return {
        "id": job.id,
        "conversation_id": job.conversation_id,
        "user_message_id": job.user_message_id,
        "status": job.status,
        "vector_saved": bool(job.vector_saved),
        "extraction_completed": bool(job.extraction_completed),
        "graph_saved": bool(job.graph_saved),
        "attempts": job.attempts,
        "last_error": job.last_error,
        "next_retry_at": job.next_retry_at,
        "completed_at": job.completed_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _get_memory_job_snapshot(job_id: str, lease_token: str | None = None) -> dict | None:
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(MemoryOutbox, job_id)
        if not job or (lease_token is not None and job.lease_token != lease_token):
            return None
        return {
            "id": job.id,
            "conversation_id": job.conversation_id,
            "user_message_id": job.user_message_id,
            "user_message": job.user_message,
            "assistant_response": job.assistant_response,
            "session_history": list(job.session_history or []),
            "neo4j_context": list(job.neo4j_context or []),
            "extracted_knowledge": job.extracted_knowledge,
            "project_id": job.project_id,
            "project_name": job.project_name,
            "scope": job.scope or "global",
            "vector_saved": bool(job.vector_saved),
            "extraction_completed": bool(job.extraction_completed),
            "graph_saved": bool(job.graph_saved),
            "status": job.status,
            "attempts": job.attempts,
            "created_at": job.created_at,
            "event_at": job.event_at or job.created_at,
            "lease_token": job.lease_token,
        }
    finally:
        db.close()


def _update_memory_job(job_id: str, *, expected_lease_token: str | None = None, **updates) -> dict | None:
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        if expected_lease_token is not None and hasattr(db, "execute"):
            result = db.query(MemoryOutbox).filter(
                MemoryOutbox.id == job_id,
                MemoryOutbox.lease_token == expected_lease_token,
            ).update(updates, synchronize_session=False)
            db.commit()
            if result != 1:
                return None
            job = db.get(MemoryOutbox, job_id)
            return _outbox_job_data(job) if job else None
        job = db.get(MemoryOutbox, job_id)
        if not job or (expected_lease_token is not None and job.lease_token != expected_lease_token):
            return None
        for field, value in updates.items():
            setattr(job, field, value)
        db.commit()
        db.refresh(job)
        return _outbox_job_data(job)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _memory_job_is_active(job_id: str, lease_token: str) -> bool:
    """Stop workers that race with a user deleting the source conversation."""
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(MemoryOutbox).filter(
            MemoryOutbox.id == job_id,
            MemoryOutbox.lease_token == lease_token,
        ).first()
        if (
            not job
            or job.lease_token != lease_token
            or job.status != "processing"
            or not job.lease_expires_at
        ):
            return False
        lease_expires_at = job.lease_expires_at
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
        if lease_expires_at <= datetime.now(timezone.utc):
            return False
        return (
            db.query(Conversation.id)
            .filter(
                Conversation.id == job.conversation_id,
                Conversation.deleted_at.is_(None),
            )
            .first()
            is not None
        )
    finally:
        db.close()


def _finish_memory_job(job_id: str, lease_token: str, stage_errors: list[str]) -> dict | None:
    """Persist a retryable final state after one independent stage pass."""
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(MemoryOutbox, job_id)
        if not job or job.status == "cancelled" or job.lease_token != lease_token:
            return _outbox_job_data(job) if job else None

        if job.vector_saved and job.extraction_completed and job.graph_saved:
            updates = {
                "status": "completed",
                "last_error": None,
                "next_retry_at": None,
                "completed_at": datetime.now(timezone.utc),
                "lease_token": None,
                "lease_expires_at": None,
            }
        else:
            delay_seconds = min(
                _MEMORY_RETRY_BASE_SECONDS * (2 ** max(job.attempts - 1, 0)),
                _MEMORY_RETRY_MAX_SECONDS,
            )
            updates = {
                "status": "failed",
                "last_error": " | ".join(stage_errors)[:4000] or "Memory job did not complete all stages",
                "next_retry_at": datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
                "lease_token": None,
                "lease_expires_at": None,
            }
        changed = db.query(MemoryOutbox).filter(
            MemoryOutbox.id == job_id,
            MemoryOutbox.lease_token == lease_token,
        ).update(updates, synchronize_session=False)
        db.commit()
        if changed != 1:
            current = db.get(MemoryOutbox, job_id)
            return _outbox_job_data(current) if current else None
        current = db.get(MemoryOutbox, job_id)
        return _outbox_job_data(current) if current else None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _claim_memory_job(job_id: str) -> str | None:
    """Atomically acquire one due job; a stale worker cannot finalize this lease."""
    from configs.database import SessionLocal

    now = datetime.now(timezone.utc)
    legacy_lease_expired_at = now - timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS)
    token = str(uuid.uuid4())
    db = SessionLocal()
    try:
        if not hasattr(db, "execute"):
            job = db.get(MemoryOutbox, job_id)
            if not job or job.status in {"completed", "cancelled"}:
                return None
            job.status = "processing"
            job.lease_token = token
            job.lease_expires_at = now + timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS)
            job.attempts += 1
            job.last_error = None
            db.commit()
            return token
        eligible = or_(
            MemoryOutbox.status == "pending",
            and_(
                MemoryOutbox.status == "failed",
                or_(MemoryOutbox.next_retry_at.is_(None), MemoryOutbox.next_retry_at <= now),
            ),
            and_(
                MemoryOutbox.status == "processing",
                or_(
                    MemoryOutbox.lease_expires_at <= now,
                    and_(
                        MemoryOutbox.lease_expires_at.is_(None),
                        MemoryOutbox.updated_at <= legacy_lease_expired_at,
                    ),
                ),
            ),
        )
        result = db.execute(
            update(MemoryOutbox)
            .where(MemoryOutbox.id == job_id, eligible)
            .values(
                status="processing",
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS),
                attempts=MemoryOutbox.attempts + 1,
                last_error=None,
                updated_at=now,
            )
        )
        db.commit()
        return token if result.rowcount == 1 else None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cancel_claim(job_id: str, lease_token: str, reason: str) -> dict | None:
    return _update_memory_job(
        job_id,
        expected_lease_token=lease_token,
        status="cancelled",
        next_retry_at=None,
        lease_token=None,
        lease_expires_at=None,
        last_error=reason,
    )


def _compensate_deleted_conversation(snapshot: dict) -> None:
    """Remove writes that crossed a deletion tombstone after an external call began."""
    delete_memory_by_session = vector_store.delete_memory_by_session

    errors: list[Exception] = []
    for operation in (
        lambda: delete_memory_by_session(snapshot["conversation_id"]),
        lambda: neo4j_client.remove_conversation_provenance(
            snapshot["conversation_id"], [snapshot["user_message_id"]]
        ),
    ):
        try:
            operation()
        except Exception as exc:
            errors.append(exc)
            logger.exception("Compensating memory cleanup failed")
    if errors:
        raise RuntimeError("Conversation was deleted and compensating cleanup was incomplete")


def _conversation_is_deleted(conversation_id: str) -> bool:
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        conversation = db.get(Conversation, conversation_id)
        return conversation is None or conversation.deleted_at is not None
    finally:
        db.close()


def _leased_memory_job_snapshot(job_id: str, lease_token: str) -> dict | None:
    """Small adapter retained for simple test doubles while enforcing leases in production."""
    try:
        return _get_memory_job_snapshot(job_id, lease_token)
    except TypeError:
        return _get_memory_job_snapshot(job_id)


def process_memory_job(job_id: str, *, report_errors: bool = False) -> dict | None:
    """Attempt every unfinished memory stage without coupling their failures.

    SQLite is the durable source of truth for this job. Qdrant and Neo4j are
    independent stores, so a failed vector upsert must not prevent extraction
    and graph persistence, and vice versa. The same job ID is reused as the
    Qdrant point ID, making a retry idempotent for the vector stage.
    """
    lease_token = _claim_memory_job(job_id)
    if lease_token is None:
        from configs.database import SessionLocal
        db = SessionLocal()
        try:
            job = db.get(MemoryOutbox, job_id)
            return _outbox_job_data(job) if job else None
        finally:
            db.close()

    snapshot = _leased_memory_job_snapshot(job_id, lease_token)
    if not snapshot or not _memory_job_is_active(job_id, lease_token):
        return _cancel_claim(job_id, lease_token, "Source conversation is deleted or lease was lost")

    stage_errors: list[str] = []
    reportable_error_logs: list[str] = []
    reportable_operation: str | None = None

    def finish_result() -> dict | None:
        result = _finish_memory_job(job_id, lease_token, stage_errors)
        if report_errors and reportable_error_logs:
            result = dict(result or {})
            result["reportable_operation"] = reportable_operation or "memory_pipeline"
            result["reportable_error_log"] = redact_diagnostic_log(
                "\n\n".join(reportable_error_logs)
            )
        return result

    # Validate extraction first in a user-facing strict run. This prevents a
    # malformed extractor result from being written to another memory store.
    if not snapshot["extraction_completed"]:
        try:
            with usage_context(conversation_id=snapshot["conversation_id"], turn_id=job_id,
                               job_id=job_id, job_attempt=snapshot.get("attempts")):
                extracted_data = extract_knowledge(
                    snapshot["user_message"],
                    neo4j_context=snapshot["neo4j_context"],
                    session_history=snapshot["session_history"],
                    raise_on_error=True,
                    project_id=snapshot.get("project_id"),
                    project_name=snapshot.get("project_name"),
                    event_at=snapshot.get("event_at"),
                )
            _update_memory_job(
                job_id,
                expected_lease_token=lease_token,
                extracted_knowledge=extracted_data,
                extraction_completed=True,
            )
        except Exception as exc:
            logger.exception("Memory job %s failed during knowledge extraction", job_id)
            stage_errors.append(f"extraction: {exc}")
            if report_errors and not isinstance(exc, MemoryLLMUnavailableError):
                reportable_operation = reportable_operation or "knowledge_extraction"
                reportable_error_logs.append(traceback.format_exc())

    if report_errors and reportable_error_logs:
        return finish_result()

    snapshot = _leased_memory_job_snapshot(job_id, lease_token)
    if not snapshot or not _memory_job_is_active(job_id, lease_token):
        return _cancel_claim(job_id, lease_token, "Source conversation is deleted or lease was lost")

    if (
        snapshot["extraction_completed"]
        and not snapshot["vector_saved"]
        and _memory_job_is_active(job_id, lease_token)
    ):
        try:
            assertion_text, assertion_spans = _vector_assertion_evidence(
                snapshot.get("extracted_knowledge")
            )
            if assertion_text:
                save_memory(
                    assertion_text,
                    {
                        "session_id": snapshot["conversation_id"],
                        "message_id": snapshot["user_message_id"],
                        "memory_job_id": job_id,
                        "source_role": "user",
                        "epistemic_status": "user_assertion",
                        "assertion_spans": assertion_spans,
                        "modality": "asserted_fact",
                        "polarity": "positive",
                        "stored_at": snapshot["created_at"].isoformat() if snapshot.get("created_at") else None,
                        "event_at": snapshot["event_at"].isoformat() if snapshot.get("event_at") else None,
                        "memory_status": "active",
                        "project_id": snapshot.get("project_id"),
                        "scope": snapshot.get("scope") or "global",
                    },
                    point_id=job_id,
                )
            else:
                logger.info("Memory job %s has no positive assertion for vector indexing", job_id)
            if not _memory_job_is_active(job_id, lease_token):
                if _conversation_is_deleted(snapshot["conversation_id"]):
                    _compensate_deleted_conversation(snapshot)
                return _cancel_claim(job_id, lease_token, "Conversation deleted during vector write")
            _update_memory_job(job_id, expected_lease_token=lease_token, vector_saved=True)
        except Exception as exc:
            logger.exception("Memory job %s failed during Qdrant upsert", job_id)
            stage_errors.append(f"vector: {exc}")
            if report_errors:
                reportable_operation = reportable_operation or "vector_memory_write"
                reportable_error_logs.append(traceback.format_exc())

    if report_errors and reportable_error_logs:
        return finish_result()

    snapshot = _leased_memory_job_snapshot(job_id, lease_token)
    if not snapshot or not _memory_job_is_active(job_id, lease_token):
        return _cancel_claim(job_id, lease_token, "Source conversation is deleted or lease was lost")

    if snapshot["extraction_completed"] and not snapshot["graph_saved"]:
        try:
            extracted_data = snapshot["extracted_knowledge"] or {"nodes": [], "edges": [], "retractions": []}
            nodes = extracted_data.get("nodes", [])
            edges = extracted_data.get("edges", [])
            retractions = extracted_data.get("retractions", [])
            graph_result = {}
            if nodes or edges or retractions:
                graph_result = neo4j_client.merge_knowledge(
                    nodes,
                    edges,
                    retractions=retractions,
                    source_conversation_id=snapshot["conversation_id"],
                    source_message_id=snapshot["user_message_id"],
                    project_id=snapshot.get("project_id"),
                    project_name=snapshot.get("project_name"),
                    event_id=job_id,
                    event_at=snapshot.get("event_at"),
                )
            if not _memory_job_is_active(job_id, lease_token):
                if _conversation_is_deleted(snapshot["conversation_id"]):
                    _compensate_deleted_conversation(snapshot)
                return _cancel_claim(job_id, lease_token, "Conversation deleted during graph write")
            invalidated_ids = list((graph_result or {}).get("invalidated_source_message_ids") or [])
            if invalidated_ids:
                set_memories_status = vector_store.set_memories_status

                set_source_messages_memory_status(invalidated_ids, "inactive")
                set_memories_status(
                    invalidated_ids,
                    status="inactive",
                    event_at=snapshot.get("event_at"),
                )
            _update_memory_job(job_id, expected_lease_token=lease_token, graph_saved=True)
        except Exception as exc:
            logger.exception("Memory job %s failed during Neo4j merge", job_id)
            stage_errors.append(f"graph: {exc}")
            if report_errors:
                reportable_operation = reportable_operation or "knowledge_graph_write"
                reportable_error_logs.append(traceback.format_exc())

    return finish_result()


def process_due_memory_jobs(limit: int = 25) -> list[dict]:
    """Retry durable jobs after a restart or exponential-backoff delay."""
    from configs.database import SessionLocal

    safe_limit = min(max(int(limit), 1), 100)
    now = datetime.now(timezone.utc)
    legacy_lease_expired_at = now - timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS)
    db = SessionLocal()
    try:
        job_ids = [
            row[0]
            for row in db.query(MemoryOutbox.id)
            .filter(
                or_(
                    MemoryOutbox.status == "pending",
                    and_(
                        MemoryOutbox.status == "failed",
                        or_(MemoryOutbox.next_retry_at.is_(None), MemoryOutbox.next_retry_at <= now),
                    ),
                    and_(
                        MemoryOutbox.status == "processing",
                        or_(
                            MemoryOutbox.lease_expires_at <= now,
                            and_(
                                MemoryOutbox.lease_expires_at.is_(None),
                                MemoryOutbox.updated_at <= legacy_lease_expired_at,
                            ),
                        ),
                    ),
                )
            )
            .order_by(MemoryOutbox.created_at.asc())
            .limit(safe_limit)
            .all()
        ]
    finally:
        db.close()

    results = []
    for job_id in job_ids:
        try:
            result = process_memory_job(job_id)
            if result:
                results.append(result)
        except Exception:
            logger.exception("Unexpected failure while retrying memory job %s", job_id)
    return results


def list_memory_jobs(limit: int = 50) -> list[dict]:
    """List job health for an authenticated operator without exposing messages."""
    from configs.database import SessionLocal

    safe_limit = min(max(int(limit), 1), 100)
    db = SessionLocal()
    try:
        jobs = (
            db.query(MemoryOutbox)
            .order_by(MemoryOutbox.updated_at.desc())
            .limit(safe_limit)
            .all()
        )
        return [_outbox_job_data(job) for job in jobs]
    finally:
        db.close()


def retry_memory_job(job_id: str) -> dict | None:
    """Make an unfinished job eligible for immediate processing again."""
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(MemoryOutbox, job_id)
        if not job:
            return None
        if job.status in {"completed", "cancelled"}:
            raise ValueError(f"Cannot retry a {job.status} memory job")
        if job.status == "processing" and job.lease_expires_at:
            lease_expires_at = job.lease_expires_at
            if lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
            if lease_expires_at > datetime.now(timezone.utc):
                raise ValueError("Cannot retry a memory job with an active lease")
        elif job.status == "processing":
            updated_at = job.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at > datetime.now(timezone.utc) - timedelta(seconds=_MEMORY_JOB_LEASE_SECONDS):
                raise ValueError("Cannot retry a recently processing memory job")
        job.status = "pending"
        job.next_retry_at = datetime.now(timezone.utc)
        job.last_error = None
        job.lease_token = None
        job.lease_expires_at = None
        db.commit()
        db.refresh(job)
        return _outbox_job_data(job)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def cancel_memory_jobs_for_conversation(session_id: str, db: Session) -> int:
    """Prevent queued work from recreating memory after a session is deleted."""
    return (
        db.query(MemoryOutbox)
        .filter(
            MemoryOutbox.conversation_id == session_id,
            MemoryOutbox.status.in_(["pending", "processing", "failed"]),
        )
        .update(
            {
                MemoryOutbox.status: "cancelled",
                MemoryOutbox.next_retry_at: None,
                MemoryOutbox.last_error: "Source conversation deleted",
                MemoryOutbox.lease_token: None,
                MemoryOutbox.lease_expires_at: None,
            },
            synchronize_session=False,
        )
    )









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
memory_workflows.process_memory_job = process_memory_job

install_facade(__name__, {
    "_resolve_project_scope": (memory_workflows, "resolve_project_scope"),
    "retrieve_context": (memory_workflows, "retrieve_context"),
    "_filter_active_vector_memories": (memory_workflows, "filter_active_vector_memories"),
    "get_session_history": (memory_workflows, "get_session_history"),
    "get_session_summary": (memory_workflows, "get_session_summary"),
    "begin_turn": (memory_workflows, "begin_turn"),
    "mark_turn_status": (memory_workflows, "mark_turn_status"),
    "save_interaction": (memory_workflows, "save_interaction"),
    "_normalized_text": (memory_workflows.scope, "normalized_text"),
    "_mentions_project_name": (memory_workflows.scope, "mentions_project_name"),
    "_is_standalone_assistant_question": (memory_workflows.retrieval, "is_standalone_assistant_question"),
    "_memory_intent_keywords": (memory_workflows.retrieval, "memory_intent_keywords"),
    "_requires_personal_memory": (memory_workflows.retrieval, "requires_personal_memory"),
    "_local_search_keywords": (memory_workflows.retrieval, "local_search_keywords"),
    "search_memory": (memory_workflows, "search_memory"),
    "search_project_memory_candidates": (memory_workflows, "search_project_memory_candidates"),
    "route_memory_query": (memory_workflows, "route_memory_query"),
    "_submit_retrieval": (memory_workflows.retrieval_executor, "submit"),
    "neo4j_client": (memory_workflows, "graph"),
    "vector_store": (memory_workflows, "vector"),
})
