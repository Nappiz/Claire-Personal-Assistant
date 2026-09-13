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
from services.qdrant_service import (
    save_memory,
    reconcile_memory,
    search_memory,
    search_project_memory_candidates,
)
from services.neo4j_service import neo4j_client
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


def _submit_retrieval(function, *args, **kwargs):
    return _MEMORY_RETRIEVAL_EXECUTOR.submit(copy_context().run, function, *args, **kwargs)


def _is_standalone_assistant_question(user_message: str) -> bool:
    """Identify questions about Claire's general identity, not user memory."""
    normalized = " ".join(user_message.lower().split())
    refers_to_claire = bool(re.search(r"\b(kamu|mu|lo|claire)\b", normalized))
    asks_about_creator = bool(
        re.search(r"\b(siapa|apa)\b.*\b(nyiptain|menciptakan|pencipta)\b", normalized)
        or re.search(r"\b(siapa|apa)\b.*\b(bikin|buat)\s+(?:kamu|claire)\s*\??$", normalized)
    )
    asks_general_identity = bool(re.search(r"\b(kamu|claire)\s+(?:itu\s+)?(?:siapa|apa)\b", normalized))
    return refers_to_claire and (asks_about_creator or asks_general_identity)


def _memory_intent_keywords(user_message: str) -> list[str]:
    """Add deterministic relation hints for common personal-memory questions.

    The LLM router often reduces Indonesian questions such as ``aku kerja di
    mana`` to only ``nafiz``. Every fact sourced by Nafiz then has the same
    lexical score and the desired relation can fall outside Neo4j's per-keyword
    limit. Relation hints use the normalized Cypher relationship names, so the
    intended fact gets its own exact lookup.
    """
    normalized = " ".join(str(user_message or "").lower().split())
    relation_rules = (
        (r"\b(pacar(?:ku|nya)?|pasangan(?:ku|nya)?|jadian|dating)\b", ["dating", "dating since"]),
        (r"\b(kerja|bekerja|magang|kantor|pekerjaan(?:ku|nya)?)\b", ["works at", "works as"]),
        (r"\b(tanggal lahir|lahir|ulang tahun|ultah)\b", ["born on", "born in"]),
        (r"\b(kuliah|kampus|mahasiswa|jurusan|semester)\b", ["studied at"]),
        (r"\b(rumah(?:ku|nya)?|tinggal|domisili)\b", ["lives in"]),
        (r"\b(asal|berasal)\b", ["originates from"]),
        (r"\b(suka|favorit|kesukaan)\b", ["likes"]),
        (r"\b(alergi)\b", ["allergic to"]),
        (r"\b(punya|memiliki|milik)\b", ["owns"]),
    )

    hints: list[str] = []
    for pattern, relation_keywords in relation_rules:
        if re.search(pattern, normalized):
            hints.extend(relation_keywords)

    refers_to_user = bool(
        re.search(r"\b(aku|saya|gw|gue|nafiz|ku)\b", normalized)
        or re.search(r"\b(pacarku|pasanganku|pekerjaanku|rumahku)\b", normalized)
    )
    if not refers_to_user:
        return []
    if hints:
        hints.append("nafiz")
    return hints


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


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _mentions_project_name(text: str, project_name: str) -> bool:
    normalized_text = _normalized_text(text)
    normalized_name = _normalized_text(project_name)
    if not normalized_name:
        return False
    return bool(
        re.search(
            rf"(?<!\w){re.escape(normalized_name)}(?!\w)",
            normalized_text,
            flags=re.UNICODE,
        )
    )


def _resolve_project_scope(
    user_message: str,
    *,
    session_project_id: str | None = None,
    session_history: list[dict] | None = None,
) -> ProjectScopeContext:
    """Resolve project references without exposing memories from every project."""
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        projects = db.query(Project).order_by(Project.updated_at.desc()).all()
        project_rows = [(str(project.id), str(project.name)) for project in projects]
    finally:
        db.close()

    if session_project_id:
        match = next((item for item in project_rows if item[0] == session_project_id), None)
        return ProjectScopeContext(
            status="resolved",
            project_id=session_project_id,
            project_name=match[1] if match else session_project_id,
            resolution="session",
        )

    named_matches = [item for item in project_rows if _mentions_project_name(user_message, item[1])]
    if len(named_matches) == 1:
        return ProjectScopeContext(
            status="resolved",
            project_id=named_matches[0][0],
            project_name=named_matches[0][1],
            resolution="message",
        )
    if len(named_matches) > 1:
        return ProjectScopeContext(
            status="ambiguous",
            candidates=[name for _, name in named_matches],
        )

    # A bare use of "project" often names a public concept (for example,
    # project management). Only possessive/deictic wording is a reference to
    # one of the user's stored projects; explicit project names were handled
    # above.
    has_owned_project_reference = bool(_VAGUE_PROJECT_REFERENCE_RE.search(user_message))
    if not has_owned_project_reference:
        return ProjectScopeContext()

    for message in reversed(list(session_history or [])[-12:]):
        content = str(message.get("content") or "") if isinstance(message, dict) else ""
        history_matches = [item for item in project_rows if _mentions_project_name(content, item[1])]
        if len(history_matches) == 1:
            return ProjectScopeContext(
                status="resolved",
                project_id=history_matches[0][0],
                project_name=history_matches[0][1],
                resolution="history",
            )

    if len(project_rows) == 1 and _VAGUE_PROJECT_REFERENCE_RE.search(user_message):
        return ProjectScopeContext(
            status="resolved",
            project_id=project_rows[0][0],
            project_name=project_rows[0][1],
            resolution="single",
        )

    if project_rows:
        try:
            evidence = search_project_memory_candidates(user_message, limit=12)
        except Exception:
            logger.exception("Project-scope semantic resolution failed")
            evidence = []
        scores: dict[str, float] = {}
        for item in evidence:
            candidate_id = str(item.get("project_id") or "")
            if candidate_id not in {project_id for project_id, _ in project_rows}:
                continue
            score = float(item.get("score") or 0.0)
            scores[candidate_id] = max(scores.get(candidate_id, -1.0), score)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        from configs.settings import settings

        resolution_min_score = min(
            max(float(settings.MEMORY_SEARCH_SCORE_THRESHOLD) + 0.03, 0.78),
            0.90,
        )
        if (
            ranked
            and ranked[0][1] >= resolution_min_score
            and (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 0.05)
        ):
            resolved_id = ranked[0][0]
            resolved_name = next(name for project_id, name in project_rows if project_id == resolved_id)
            return ProjectScopeContext(
                status="resolved",
                project_id=resolved_id,
                project_name=resolved_name,
                resolution="semantic",
            )

    return ProjectScopeContext(
        status="ambiguous",
        candidates=[name for _, name in project_rows[:8]],
    )


def _requires_personal_memory(user_message: str) -> bool:
    normalized = " ".join(str(user_message or "").lower().split())
    return bool(_MEMORY_RECALL_RE.search(normalized) or _memory_intent_keywords(normalized))


def _local_search_keywords(user_message: str) -> list[str]:
    """Produce a useful graph query even if the LLM router is unavailable."""
    normalized = " ".join(str(user_message or "").lower().split())
    keywords = list(_memory_intent_keywords(normalized))
    if re.search(r"\b(aku|saya|gw|gue|ku)\b", normalized):
        keywords.append("nafiz")
    for token in re.findall(r"[a-zA-Z0-9_-]+", normalized):
        if len(token) >= 3 and token not in _SEARCH_STOPWORDS:
            keywords.append(token)

    deduplicated: list[str] = []
    for keyword in keywords:
        clean_keyword = " ".join(keyword.lower().split())[:100]
        if clean_keyword and clean_keyword not in deduplicated:
            deduplicated.append(clean_keyword)
    return deduplicated[:8]


def _filter_active_vector_memories(items: list[dict]) -> list[dict]:
    """Reject stale vectors even when an older Qdrant payload lacks lifecycle metadata."""
    if not items:
        return []
    from configs.database import SessionLocal

    message_ids = {str(item.get("message_id")) for item in items if item.get("message_id")}
    if not message_ids:
        return []
    db = SessionLocal()
    try:
        active_ids = {
            str(row[0])
            for row in (
                db.query(Message.id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .filter(
                    Message.id.in_(message_ids),
                    Message.role == "user",
                    Message.message_type == "normal",
                    Message.memory_status == "active",
                    Conversation.deleted_at.is_(None),
                )
                .all()
            )
        }
    finally:
        db.close()
    return [item for item in items if str(item.get("message_id") or "") in active_ids]


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

def retrieve_context(
    user_message: str,
    *,
    raise_on_error: bool = False,
    project_id: str | None = None,
    session_history: list[dict] | None = None,
    session_summary: str | None = None,
) -> MemoryContext:
    """
    Mengambil konteks dari Neo4j (Long-term Facts) dan Qdrant (Semantic Search).
    Router terlebih dahulu menentukan apakah pesan memang membutuhkan memori.
    Ini penting untuk pertanyaan mandiri seperti "siapa penciptamu?": hasil
    vector search yang kebetulan mirip tidak boleh mengalihkan topik jawaban.
    """
    logger.info("Retrieving context with an end-to-end deadline")
    if _is_standalone_assistant_question(user_message):
        logger.info("Skipping memory retrieval for standalone question about Claire.")
        return MemoryContext(qdrant_context=[], neo4j_context=[])
    timeout_seconds = max(float(settings.MEMORY_RETRIEVAL_TIMEOUT_SECONDS), 0.1)
    deadline = time.monotonic() + timeout_seconds
    warnings: list[str] = []
    diagnostics: list[str] = []

    scope_future = _submit_retrieval(
        _resolve_project_scope,
        user_message,
        session_project_id=project_id,
        session_history=session_history,
    )
    route_future = _submit_retrieval(
        route_memory_query, user_message, session_history=session_history, session_summary=session_summary
    )
    concurrent.futures.wait(
        (scope_future, route_future),
        timeout=max(deadline - time.monotonic(), 0.0),
    )

    if scope_future.done():
        try:
            project_scope = scope_future.result()
        except Exception:
            diagnostics.append(traceback.format_exc())
            warnings.append("project_scope_unavailable")
            project_scope = ProjectScopeContext(
                status="resolved" if project_id else ("ambiguous" if _VAGUE_PROJECT_REFERENCE_RE.search(user_message) else "none"),
                project_id=project_id,
                project_name=project_id,
                resolution="session" if project_id else None,
            )
    else:
        scope_future.cancel()
        warnings.append("project_scope_timeout")
        diagnostics.append(f"Project scope resolution exceeded the {timeout_seconds}s retrieval deadline.")
        project_scope = ProjectScopeContext(
            status="resolved" if project_id else ("ambiguous" if _VAGUE_PROJECT_REFERENCE_RE.search(user_message) else "none"),
            project_id=project_id,
            project_name=project_id,
            resolution="session" if project_id else None,
        )

    if route_future.done():
        try:
            route = route_future.result()
        except Exception as exc:
            diagnostics.append(traceback.format_exc())
            route = type("RouteFallback", (), {"status": "router_failed", "keywords": [], "error": str(exc)})()
    else:
        route_future.cancel()
        warnings.append("memory_router_timeout")
        diagnostics.append(f"Memory router exceeded the {timeout_seconds}s retrieval deadline.")
        route = type("RouteFallback", (), {"status": "router_failed", "keywords": [], "error": "timeout"})()

    effective_project_id = project_scope.project_id
    query_resolution = QueryResolution(
        status=("ambiguous" if route.status == "router_failed" and _reference_matches(user_message)
                else getattr(route, "reference_status", "none")),
        query=getattr(route, "query", None) or user_message,
        candidates=list(getattr(route, "candidates", ())),
        confidence=getattr(route, "confidence", 0.0),
    )
    if query_resolution.status == "ambiguous":
        return MemoryContext(
            project_scope=project_scope, query_resolution=query_resolution,
            retrieval_status=RetrievalStatus(
                router="router_failed" if route.status == "router_failed" else "forced",
                router_available=route.status != "router_failed", warnings=["memory_reference_ambiguous"],
            ),
        )
    retrieval_query = query_resolution.query

    intent_keywords = _memory_intent_keywords(retrieval_query)
    deterministic_recall = _requires_personal_memory(retrieval_query)
    if route.status == "router_failed":
        router_state = "router_failed"
        should_retrieve = True
        router_keywords = _local_search_keywords(retrieval_query)
    elif route.status == "needed":
        router_state = "needed"
        should_retrieve = True
        router_keywords = route.keywords
    elif effective_project_id or project_scope.status == "ambiguous" or deterministic_recall or intent_keywords:
        router_state = "forced"
        should_retrieve = True
        router_keywords = _local_search_keywords(retrieval_query)
    else:
        return MemoryContext(
            retrieval_status=RetrievalStatus(router="not_needed"),
            project_scope=project_scope,
            query_resolution=query_resolution,
        )

    keywords = []
    for keyword in [*intent_keywords, *router_keywords]:
        normalized_keyword = " ".join(str(keyword or "").lower().split())
        if normalized_keyword and normalized_keyword not in keywords:
            keywords.append(normalized_keyword)
    logger.info(
        "Generated RAG Keywords: intent=%s router=%s combined=%s",
        intent_keywords,
        router_keywords,
        keywords,
    )
    if not keywords:
        keywords = _local_search_keywords(retrieval_query)

    if not should_retrieve:
        return MemoryContext(retrieval_status=RetrievalStatus(router="not_needed"))

    qdrant_results: list[dict] = []
    neo4j_results: list[str] = []
    qdrant_available = True
    neo4j_available = True
    include_historical = bool(_HISTORICAL_RE.search(user_message.lower()))

    remaining = max(deadline - time.monotonic(), 0.0)
    if remaining <= 0:
        future_qdrant = future_neo4j = None
        warnings.extend(["semantic_memory_timeout", "knowledge_graph_timeout"])
        diagnostics.append("The retrieval deadline was exhausted by routing and scope resolution.")
    else:
        completed: set[concurrent.futures.Future] = set()
        future_qdrant = _submit_retrieval(
            search_memory,
            retrieval_query,
            3,
            project_id=effective_project_id,
        )
        future_neo4j = _submit_retrieval(
            neo4j_client.search_knowledge,
            keywords,
            include_historical=include_historical,
            project_id=effective_project_id,
        )
        completed, _ = concurrent.futures.wait(
            (future_qdrant, future_neo4j),
            timeout=max(deadline - time.monotonic(), 0.0),
        )
    if future_qdrant is not None:
        if future_qdrant not in completed:
            qdrant_available = False
            warnings.append("semantic_memory_timeout")
            diagnostics.append(
                "Qdrant semantic-memory retrieval exceeded "
                f"{settings.MEMORY_RETRIEVAL_TIMEOUT_SECONDS} seconds."
            )
            future_qdrant.cancel()
        else:
            try:
                qdrant_results = future_qdrant.result()
            except Exception as exc:
                qdrant_available = False
                warnings.append("semantic_memory_unavailable")
                diagnostics.append(traceback.format_exc())
                logger.exception("Qdrant retrieval failed; continuing with remaining context: %s", exc)

    if future_neo4j is not None:
        if future_neo4j not in completed:
            neo4j_available = False
            warnings.append("knowledge_graph_timeout")
            diagnostics.append(
                "Neo4j knowledge-graph retrieval exceeded "
                f"{settings.MEMORY_RETRIEVAL_TIMEOUT_SECONDS} seconds."
            )
            future_neo4j.cancel()
        else:
            try:
                neo4j_results = future_neo4j.result()
            except Exception as exc:
                neo4j_available = False
                warnings.append("knowledge_graph_unavailable")
                diagnostics.append(traceback.format_exc())
                logger.exception("Neo4j retrieval failed; continuing with remaining context: %s", exc)
    else:
        neo4j_available = False

    qdrant_timed_out = future_qdrant is None
    if qdrant_timed_out:
        qdrant_available = False

    qdrant_results = _filter_active_vector_memories(qdrant_results)

    if not qdrant_available and not neo4j_available:
        warnings.append("memory_backends_unavailable")

    if raise_on_error and diagnostics:
        raise InternalFeatureError(
            "memory_retrieval",
            "Pengambilan konteks memori gagal atau melewati batas waktu.",
            redact_diagnostic_log("\n\n".join(diagnostics)),
        )

    context = MemoryContext(
        qdrant_context=qdrant_results,
        neo4j_context=neo4j_results,
        retrieval_status=RetrievalStatus(
            router=router_state,
            router_available=router_state != "router_failed",
            qdrant_available=qdrant_available,
            neo4j_available=neo4j_available,
            degraded=not (qdrant_available and neo4j_available),
            warnings=warnings,
        ),
        project_scope=project_scope,
        query_resolution=query_resolution,
    )
    return context

def get_session_history(db: Session, session_id: str, limit: int = 30):
    """
    Mengambil N pesan terakhir dari sebuah sesi (Short-Term Memory).
    """
    if not session_id:
        return []
        
    messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == session_id,
            Message.message_type == "normal",
        )
        .order_by(*Message.chronological_order(descending=True))
        .limit(limit)
        .all()
    )
    
    history = []
    for msg in reversed(messages):
        history.append({"role": msg.role, "content": msg.content})
        
    return history


def get_session_summary(db: Session, session_id: str) -> str:
    if not session_id:
        return ""
    row = db.query(Conversation.summary).filter(Conversation.id == session_id).first()
    return str(row[0] or "") if row else ""

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
    from services.qdrant_service import delete_memory_by_session

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
                from services.qdrant_service import set_memories_status

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

class TurnConflictError(RuntimeError):
    """Raised when one conversation already has another unfinished turn."""


def begin_turn(session_id: str, user_message: str, turn_id: str) -> dict:
    """Persist and sequence a user turn before retrieval or provider I/O."""
    from configs.database import SessionLocal

    db = SessionLocal()
    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .with_for_update()
            .first()
        )
        if conversation is None:
            raise ValueError("Session not found or has been deleted")
        previous_active_turn_id = conversation.active_turn_id

        existing_user = (
            db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            )
            .first()
        )
        existing_assistant = (
            db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "assistant",
            )
            .first()
        )
        if existing_user is not None and existing_user.content != user_message:
            raise TurnConflictError("turn_id was already used for different content")
        if existing_assistant is not None and existing_assistant.message_type == "normal":
            return {
                "turn_id": turn_id,
                "turn_sequence": existing_assistant.turn_sequence,
                "user_message_id": str(existing_user.id) if existing_user else None,
                "cached_reply": existing_assistant.content,
                "completed": True,
                "response_status": existing_assistant.response_status or "complete",
                "finish_reason": existing_assistant.finish_reason,
            }
        claimed = db.execute(
            update(Conversation)
            .where(
                Conversation.id == session_id,
                Conversation.deleted_at.is_(None),
                or_(
                    Conversation.active_turn_id.is_(None),
                    Conversation.active_turn_id == turn_id,
                    Conversation.active_turn_expires_at.is_(None),
                    Conversation.active_turn_expires_at <= datetime.now(timezone.utc),
                ),
            )
            .values(
                active_turn_id=turn_id,
                active_turn_expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=max(int(settings.TURN_LEASE_SECONDS), 60)),
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            raise TurnConflictError("Another turn is already active for this conversation")
        if previous_active_turn_id and previous_active_turn_id != turn_id:
            db.query(Message).filter(
                Message.conversation_id == session_id,
                Message.turn_id == previous_active_turn_id,
                Message.role == "user",
                Message.message_type == "pending_turn",
            ).update(
                {Message.message_type: "interrupted_turn"},
                synchronize_session=False,
            )
        db.expire_all()
        conversation = db.get(Conversation, session_id)
        existing_user = (
            db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            )
            .first()
        )
        existing_assistant = (
            db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "assistant",
            )
            .first()
        )
        if existing_assistant is not None and existing_assistant.message_type == "normal":
            conversation.active_turn_id = None
            conversation.active_turn_expires_at = None
            db.commit()
            return {
                "turn_id": turn_id,
                "turn_sequence": existing_assistant.turn_sequence,
                "user_message_id": str(existing_user.id) if existing_user else None,
                "cached_reply": existing_assistant.content,
                "completed": True,
                "response_status": existing_assistant.response_status or "complete",
                "finish_reason": existing_assistant.finish_reason,
            }

        if existing_user is None:
            sequence = int(conversation.next_turn_sequence or 1)
            existing_user = Message(
                conversation_id=session_id,
                role="user",
                content=user_message,
                message_type="pending_turn",
                turn_id=turn_id,
                turn_sequence=sequence,
            )
            db.add(existing_user)
            conversation.next_turn_sequence = sequence + 1
            conversation.message_count = int(conversation.message_count or 0) + 1
        else:
            sequence = int(existing_user.turn_sequence or conversation.next_turn_sequence or 1)
            existing_user.turn_sequence = sequence
            existing_user.message_type = "pending_turn"
            conversation.next_turn_sequence = max(int(conversation.next_turn_sequence or 1), sequence + 1)

        conversation.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing_user)
        return {
            "turn_id": turn_id,
            "turn_sequence": sequence,
            "user_message_id": str(existing_user.id),
            "cached_reply": None,
            "completed": False,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_turn_status(session_id: str, turn_id: str, status: str, details: dict | None = None) -> None:
    """Release a turn lease while keeping its durable user message retryable."""
    from configs.database import SessionLocal

    if status not in {"interrupted_turn", "failed_turn", "pending_turn"}:
        raise ValueError("Unsupported turn status")
    db = SessionLocal()
    try:
        message = (
            db.query(Message)
            .filter(
                Message.conversation_id == session_id,
                Message.turn_id == turn_id,
                Message.role == "user",
            )
            .first()
        )
        conversation = db.get(Conversation, session_id)
        if message and message.message_type != "normal":
            message.message_type = status
            message.error_details = details
        if conversation and conversation.active_turn_id == turn_id:
            conversation.active_turn_id = None
            conversation.active_turn_expires_at = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_interaction(
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
    from configs.database import SessionLocal
    from services.llm_service import ERROR_FALLBACK_MSG
    response_status = usage.get("response_status", response_status) if usage else response_status
    finish_reason = usage.get("finish_reason", finish_reason) if usage else finish_reason
    if str(finish_reason or "").lower() in {"length", "max_tokens", "max_output_tokens", "content_filter"}:
        response_status = "incomplete"
    if response_status not in {"complete", "incomplete"}:
        raise ValueError("Invalid AI response status")

    db = SessionLocal()
    assistant_message_id: str | None = None
    memory_job_id: str | None = None
    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .with_for_update()
            .first()
        )
        if conversation is None:
            raise ValueError("Session was deleted before the turn could be committed")

        msg_user = db.get(Message, user_message_id) if user_message_id else None
        if turn_id and msg_user is None:
            msg_user = (
                db.query(Message)
                .filter(
                    Message.conversation_id == session_id,
                    Message.turn_id == turn_id,
                    Message.role == "user",
                )
                .first()
            )
        created_user = False
        if msg_user is None:
            sequence = int(turn_sequence or conversation.next_turn_sequence or 1)
            msg_user = Message(
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
                db.query(Message)
                .filter(
                    Message.conversation_id == session_id,
                    Message.turn_id == turn_id,
                    Message.role == "assistant",
                )
                .first()
            )
        created_assistant = False
        if msg_ai is None:
            assistant_created_at = datetime.now(timezone.utc)
            user_created_at = msg_user.created_at
            if user_created_at and user_created_at.tzinfo is None:
                user_created_at = user_created_at.replace(tzinfo=timezone.utc)
            if user_created_at and assistant_created_at <= user_created_at:
                assistant_created_at = user_created_at + timedelta(microseconds=1)
            msg_ai = Message(
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
                LLMUsageLog(
                    provider=llm_provider or "unknown",
                    model=llm_model or "unknown",
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_cost=None,
                    conversation_id=session_id,
                )
            )

        if ai_response != ERROR_FALLBACK_MSG:
            memory_job = db.get(MemoryOutbox, turn_id) if turn_id else None
            if memory_job is None:
                neo4j_ctx = context.neo4j_context if context and hasattr(context, "neo4j_context") else []
                memory_job = MemoryOutbox(
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
        job_result = process_memory_job(memory_job_id, report_errors=report_errors)
    return {
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "memory_job_id": memory_job_id,
        "memory_job": job_result,
        "summary_pending": True,
    }


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
                from services.qdrant_service import set_memories_status
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
