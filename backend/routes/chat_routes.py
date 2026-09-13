import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError
from sqlalchemy.orm import Session
from schemas.chat_sch import (
    ChatRequest,
    ChatResponse,
    ConversationPinUpdate,
    ProjectCreate,
    ProjectUpdate,
    GraphFactUpdate,
    GraphNodeUpdate,
)
from services import memory_service, llm_service
from services.ai_usage_service import set_usage_context, reset_usage_context
from services.diagnostic_service import (
    InternalFeatureError,
    current_exception_log,
    redact_diagnostic_log,
)
from configs.database import SessionLocal, get_db
from models.conversation import Conversation
from models.project import Project
from sqlalchemy.exc import IntegrityError
import uuid
from datetime import datetime, timezone

router = APIRouter()


def _sse_data(payload: dict) -> str:
    """Serialize one JSON payload as a standards-compliant SSE event."""
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _upstream_error_payload(exc: Exception, session_id: str) -> dict:
    """Map provider failures to stable, frontend-safe error codes."""
    exception_name = type(exc).__name__.lower()
    if isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError) or "timeout" in exception_name:
        code = "UPSTREAM_TIMEOUT"
        message = "The LLM provider timed out before completing the response."
    elif isinstance(exc, APIConnectionError) or any(
        marker in exception_name
        for marker in ("connection", "connecterror", "readerror", "protocolerror", "endofstream")
    ):
        code = "UPSTREAM_CONNECTION_ERROR"
        message = "The connection to the LLM provider was interrupted."
    elif isinstance(exc, APIStatusError):
        code = "UPSTREAM_HTTP_ERROR"
        message = f"The LLM provider rejected the request (HTTP {exc.status_code})."
    else:
        code = "UPSTREAM_ERROR"
        message = "The LLM stream ended unexpectedly."

    return {
        "type": "error",
        "session_id": session_id,
        "error": {"code": code, "message": message},
    }


def _is_llm_provider_error(exc: Exception) -> bool:
    """Keep provider/API failures on the existing model-failover path."""
    exception_name = type(exc).__name__.lower()
    return (
        isinstance(exc, (APIConnectionError, APIStatusError, APITimeoutError, TimeoutError))
        or any(
            marker in exception_name
            for marker in ("connection", "connecterror", "readerror", "protocolerror", "endofstream")
        )
        or str(exc) == "The upstream LLM returned an empty response"
    )


async def _internal_error_payload(
    exc: InternalFeatureError,
    session_id: str,
    *,
    model: str | None,
    provider: str | None,
) -> dict:
    """Build a terminal diagnostic event; analyzer failures never hide the log."""
    try:
        analysis = await llm_service.analyze_internal_error(
            operation=exc.operation,
            diagnostic_log=exc.diagnostic_log,
            model=model,
            provider=provider,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "The LLM diagnostic analysis was unavailable for %s",
            exc.operation,
            exc_info=True,
        )
        analysis = (
            "Aku mendeteksi kegagalan internal pada proses ini, tetapi analisis "
            "otomatisnya tidak tersedia. Detail teknis lengkapnya tetap tercantum di bawah."
        )

    return {
        "type": "internal_error",
        "session_id": session_id,
        "error": {
            "code": "INTERNAL_FEATURE_ERROR",
            "operation": exc.operation,
            "message": str(exc),
            "analysis": analysis,
            "log": redact_diagnostic_log(exc.diagnostic_log),
        },
    }


def _prepare_stream_session(
    request: ChatRequest,
) -> tuple[str, bool, list[dict], str, str | None, str | None, str, dict]:
    """Perform synchronous SQLAlchemy work outside the event-loop thread."""
    db = SessionLocal()
    try:
        session_id = request.session_id
        should_generate_title = False
        project = None
        if request.project_id:
            project = db.get(Project, request.project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
        if not session_id:
            conversation = Conversation(
                title="New Chat...",
                project_id=project.id if project else None,
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            session_id = conversation.id
            should_generate_title = True
        else:
            conversation = db.query(Conversation).filter(
                Conversation.id == session_id,
                Conversation.deleted_at.is_(None),
            ).first()
            if conversation is None:
                raise HTTPException(status_code=404, detail="Session not found")
            if request.project_id and request.project_id != conversation.project_id:
                raise HTTPException(
                    status_code=409,
                    detail="Session belongs to a different project",
                )
            project = conversation.project
            should_generate_title = (
                conversation.message_count == 0 and conversation.title == "New Chat..."
            )
            conversation.updated_at = datetime.now(timezone.utc)
            db.commit()

        turn_id = request.turn_id or str(uuid.uuid4())
        turn_state = memory_service.begin_turn(session_id, request.message, turn_id)
        session_history = memory_service.get_session_history(db, session_id, limit=200)
        session_summary = memory_service.get_session_summary(db, session_id)
        return (
            session_id,
            should_generate_title,
            session_history,
            session_summary,
            conversation.project_id,
            project.name if project else None,
            turn_id,
            turn_state,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Run one durable, idempotent chat turn."""
    session_id = request.session_id
    is_new_session = False
    if not session_id:
        project = db.get(Project, request.project_id) if request.project_id else None
        if request.project_id and project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        conversation = Conversation(title="New Chat...", project_id=project.id if project else None)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        session_id = conversation.id
        is_new_session = True
    else:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == session_id, Conversation.deleted_at.is_(None))
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if request.project_id and request.project_id != conversation.project_id:
            raise HTTPException(status_code=409, detail="Session belongs to a different project")
        project = conversation.project

    turn_id = request.turn_id or str(uuid.uuid4())
    try:
        turn_state = await run_in_threadpool(
            memory_service.begin_turn, session_id, request.message, turn_id
        )
    except memory_service.TurnConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if turn_state.get("completed"):
        return ChatResponse(
            reply=str(turn_state["cached_reply"]),
            session_id=session_id,
            turn_id=turn_id,
            context_used={},
            response_status=turn_state.get("response_status", "complete"),
            finish_reason=turn_state.get("finish_reason"),
        )

    session_history = memory_service.get_session_history(db, session_id, limit=200)
    session_summary = memory_service.get_session_summary(db, session_id)
    active_project_id = conversation.project_id
    active_project_name = project.name if project else None
    usage_token = set_usage_context(conversation_id=session_id, turn_id=turn_id, job_id=None, job_attempt=None)
    try:
        context = await run_in_threadpool(
            memory_service.retrieve_context,
            request.message,
            project_id=active_project_id,
            session_history=session_history,
            session_summary=session_summary,
        )
        effective_project_id = context.project_scope.project_id or active_project_id
        effective_project_name = context.project_scope.project_name or active_project_name
        reply_parts: list[str] = []
        usage: dict = {}
        completion = {"response_status": "complete", "finish_reason": None}
        async for event in llm_service.generate_chat_response_stream(
            request.message,
            context,
            session_history,
            model=request.model,
            provider=request.provider,
            session_summary=session_summary,
            project_id=effective_project_id,
            project_name=effective_project_name,
        ):
            if event["type"] == "delta":
                reply_parts.append(event["delta"])
            elif event["type"] == "usage":
                usage = event["usage"]
            elif event["type"] == "completion":
                completion = {key: event[key] for key in ("response_status", "finish_reason")}
        reply = "".join(reply_parts)
        if not reply:
            raise RuntimeError("The upstream LLM returned an empty response")

        persistence = await run_in_threadpool(
            memory_service.save_interaction,
            session_id=session_id,
            user_message=request.message,
            ai_response=reply,
            usage=usage,
            context=context,
            session_history=session_history,
            session_summary=session_summary,
            llm_provider=request.provider or "google",
            llm_model=request.model or llm_service.DEFAULT_MODEL_NAME,
            project_id=effective_project_id,
            project_name=effective_project_name,
            turn_id=turn_id,
            turn_sequence=turn_state["turn_sequence"],
            user_message_id=turn_state["user_message_id"],
            process_memory=False,
            **completion,
        )
    except Exception as exc:
        await run_in_threadpool(
            memory_service.mark_turn_status,
            session_id,
            turn_id,
            "failed_turn",
            {"error": type(exc).__name__},
        )
        raise

    finally:
        reset_usage_context(usage_token)

    if persistence.get("memory_job_id"):
        background_tasks.add_task(memory_service.process_memory_job, persistence["memory_job_id"])
    background_tasks.add_task(memory_service.process_conversation_summary, session_id)
    if is_new_session:
        background_tasks.add_task(
            memory_service.generate_and_save_title,
            session_id=session_id,
            first_message=request.message,
        )
    return ChatResponse(reply=reply, session_id=session_id, turn_id=turn_id, context_used=context, **completion)


@router.post("/chat/stream")
async def stream_chat_endpoint(
    request: ChatRequest,
    client_request: Request,
    background_tasks: BackgroundTasks,
):
    """Stream an OpenAI-compatible chat completion to the browser as SSE."""
    try:
        prepared_session = await run_in_threadpool(_prepare_stream_session, request)
        session_id, should_generate_title, session_history, session_summary = prepared_session[:4]
        active_project_id = prepared_session[4] if len(prepared_session) > 4 else None
        active_project_name = prepared_session[5] if len(prepared_session) > 5 else None
        turn_id = prepared_session[6] if len(prepared_session) > 6 else (request.turn_id or str(uuid.uuid4()))
        turn_state = prepared_session[7] if len(prepared_session) > 7 else {
            "turn_id": turn_id,
            "turn_sequence": None,
            "user_message_id": None,
            "completed": False,
        }
    except memory_service.TurnConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        internal_exc = InternalFeatureError(
            "chat_session",
            f"Sesi chat gagal disiapkan: {exc}",
            current_exception_log(),
        )

        async def failed_session_stream():
            yield _sse_data(
                await _internal_error_payload(
                    internal_exc,
                    request.session_id or "",
                    model=request.model,
                    provider=request.provider,
                )
            )

        return StreamingResponse(
            failed_session_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def finalize_internal_error(
        exc: InternalFeatureError,
        persistence: dict,
    ) -> dict:
        payload = await _internal_error_payload(
            exc,
            session_id,
            model=request.model,
            provider=request.provider,
        )
        error_details = dict(payload["error"])
        try:
            await run_in_threadpool(
                memory_service.record_internal_error,
                session_id=session_id,
                user_message=request.message,
                analysis=error_details["analysis"],
                error_details=error_details,
                user_message_id=persistence.get("user_message_id"),
                assistant_message_id=persistence.get("assistant_message_id"),
                memory_job_id=persistence.get("memory_job_id"),
                turn_id=turn_id,
                turn_sequence=turn_state.get("turn_sequence"),
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not persist internal error event for session %s", session_id
            )
        if should_generate_title:
            background_tasks.add_task(
                memory_service.generate_and_save_title,
                session_id=session_id,
                first_message=request.message,
            )
        return payload

    async def event_stream():
        reply_parts: list[str] = []
        usage: dict = {}
        persistence: dict = {}
        turn_finalized = False
        usage_token = None
        completion = {"response_status": "complete", "finish_reason": None}

        # Send the session immediately, before memory retrieval or the upstream
        # connection, so the UI can retain it across provider failover attempts.
        yield _sse_data({"type": "session", "session_id": session_id, "turn_id": turn_id})

        try:
            usage_token = set_usage_context(conversation_id=session_id, turn_id=turn_id, job_id=None, job_attempt=None)
            if turn_state.get("completed"):
                cached_reply = str(turn_state.get("cached_reply") or "")
                if cached_reply:
                    yield _sse_data({"type": "delta", "delta": cached_reply})
                yield _sse_data(
                    {
                        "type": "done",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "usage": {},
                        "memory_status": {},
                        "web_search": {},
                        "response_status": turn_state.get("response_status", "complete"),
                        "finish_reason": turn_state.get("finish_reason"),
                    }
                )
                turn_finalized = True
                return
            if await client_request.is_disconnected():
                await run_in_threadpool(
                    memory_service.mark_turn_status,
                    session_id,
                    turn_id,
                    "interrupted_turn",
                )
                return

            context = await run_in_threadpool(
                memory_service.retrieve_context,
                request.message,
                raise_on_error=False,
                project_id=active_project_id,
                session_history=session_history,
                session_summary=session_summary,
            )
            effective_project_id = context.project_scope.project_id or active_project_id
            effective_project_name = context.project_scope.project_name or active_project_name

            async for event in llm_service.generate_chat_response_stream(
                request.message,
                context,
                session_history,
                model=request.model,
                provider=request.provider,
                session_summary=session_summary,
                project_id=effective_project_id,
                project_name=effective_project_name,
            ):
                if await client_request.is_disconnected():
                    await run_in_threadpool(
                        memory_service.mark_turn_status,
                        session_id,
                        turn_id,
                        "interrupted_turn",
                    )
                    return

                if event["type"] == "web_search":
                    yield _sse_data(event)
                    continue

                if event["type"] == "usage":
                    usage = event["usage"]
                    continue
                if event["type"] == "completion":
                    completion = {key: event[key] for key in ("response_status", "finish_reason")}
                    continue

                delta = event["delta"]
                reply_parts.append(delta)
                yield _sse_data({"type": "delta", "delta": delta})

            reply = "".join(reply_parts)
            if not reply:
                raise RuntimeError("The upstream LLM returned an empty response")

            try:
                persistence = await run_in_threadpool(
                    memory_service.save_interaction,
                    session_id=session_id,
                    user_message=request.message,
                    ai_response=reply,
                    usage=usage,
                    context=context,
                    session_history=session_history,
                    session_summary=session_summary,
                    llm_provider=request.provider or "google",
                    llm_model=request.model or llm_service.DEFAULT_MODEL_NAME,
                    report_errors=False,
                    project_id=effective_project_id,
                    project_name=effective_project_name,
                    turn_id=turn_id,
                    turn_sequence=turn_state["turn_sequence"],
                    user_message_id=turn_state["user_message_id"],
                    process_memory=False,
                    **completion,
                )
            except Exception as exc:
                logging.getLogger(__name__).exception(
                    "Chat persistence failed for session %s", session_id
                )
                raise InternalFeatureError.from_active_exception(
                    "chat_persistence",
                    f"Penyimpanan interaksi gagal: {exc}",
                ) from exc

            if persistence.get("memory_job_id"):
                background_tasks.add_task(
                    memory_service.process_memory_job,
                    persistence["memory_job_id"],
                )
            background_tasks.add_task(
                memory_service.process_conversation_summary,
                session_id,
            )

            if should_generate_title:
                background_tasks.add_task(
                    memory_service.generate_and_save_title,
                    session_id=session_id,
                    first_message=request.message,
                )

            yield _sse_data(
                {
                    "type": "done",
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "usage": usage,
                    "memory_status": context.retrieval_status.model_dump(),
                    "web_search": context.web_context.model_dump(),
                    **completion,
                }
            )
            turn_finalized = True
        except InternalFeatureError as exc:
            logging.getLogger(__name__).exception(
                "Internal chat feature failed for session %s (%s)",
                session_id,
                exc.operation,
            )
            yield _sse_data(await finalize_internal_error(exc, persistence))
            turn_finalized = True
        except Exception as exc:
            if _is_llm_provider_error(exc):
                logging.getLogger(__name__).exception(
                    "Streaming LLM request failed for session %s", session_id
                )
                await run_in_threadpool(
                    memory_service.mark_turn_status,
                    session_id,
                    turn_id,
                    "interrupted_turn",
                    {"error": type(exc).__name__},
                )
                payload = _upstream_error_payload(exc, session_id)
                payload["turn_id"] = turn_id
                yield _sse_data(payload)
                turn_finalized = True
            else:
                logging.getLogger(__name__).exception(
                    "Unexpected internal chat failure for session %s", session_id
                )
                internal_exc = InternalFeatureError(
                    "chat_pipeline",
                    f"Pipeline chat mengalami error internal: {exc}",
                    current_exception_log(),
                )
                yield _sse_data(await finalize_internal_error(internal_exc, persistence))
                turn_finalized = True
        finally:
            if not turn_finalized:
                try:
                    await run_in_threadpool(
                        memory_service.mark_turn_status,
                        session_id,
                        turn_id,
                        "interrupted_turn",
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not release interrupted turn %s", turn_id
                    )
            if usage_token is not None:
                reset_usage_context(usage_token)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

from models.message import Message

@router.get("/sessions")
def get_sessions(db: Session = Depends(get_db)):
    """Mendapatkan daftar semua sesi obrolan (terbaru di atas)"""
    convs = (
        db.query(Conversation)
        .filter(Conversation.deleted_at.is_(None))
        .order_by(
            Conversation.is_pinned.desc(),
            Conversation.pinned_at.desc(),
            Conversation.updated_at.desc(),
        )
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "is_pinned": bool(c.is_pinned),
            "pinned_at": c.pinned_at,
            "project_id": c.project_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at
        } for c in convs
    ]


@router.get("/projects")
def get_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    return [
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "session_count": sum(1 for item in project.conversations if item.deleted_at is None),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
        for project in projects
    ]


@router.post("/projects", status_code=201)
def create_project(request: ProjectCreate, db: Session = Depends(get_db)):
    name = " ".join(request.name.split())
    project = Project(name=name, description=(request.description or "").strip() or None)
    db.add(project)
    try:
        db.commit()
        db.refresh(project)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists") from exc
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "session_count": 0,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    request: ProjectUpdate,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = request.model_dump(exclude_unset=True)
    if "name" in updates:
        project.name = " ".join(updates["name"].split())
    if "description" in updates:
        project.description = (updates["description"] or "").strip() or None
    try:
        db.commit()
        db.refresh(project)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists") from exc
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "session_count": len(project.conversations),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if any(item.deleted_at is None for item in project.conversations):
        raise HTTPException(
            status_code=409,
            detail="Delete or move every session in this project first",
        )
    db.delete(project)
    db.commit()
    return {"message": "Project deleted"}


@router.patch("/sessions/{session_id}/pin")
def set_session_pin(
    session_id: str,
    request: ConversationPinUpdate,
    db: Session = Depends(get_db),
):
    """Pin or unpin a conversation in the history sidebar."""
    conversation = db.get(Conversation, session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")

    conversation.is_pinned = request.is_pinned
    conversation.pinned_at = datetime.now(timezone.utc) if request.is_pinned else None
    db.commit()
    db.refresh(conversation)
    return {
        "id": conversation.id,
        "is_pinned": bool(conversation.is_pinned),
        "pinned_at": conversation.pinned_at,
    }

@router.get("/history/{session_id}")
def get_history(session_id: str, db: Session = Depends(get_db)):
    """Mendapatkan riwayat obrolan lengkap dari sesi tertentu"""
    active = db.query(Conversation.id).filter(
        Conversation.id == session_id,
        Conversation.deleted_at.is_(None),
    ).first()
    if active is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.query(Message).filter(Message.conversation_id == session_id).order_by(*Message.chronological_order()).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "message_type": m.message_type,
            "internal_error": m.error_details,
            "created_at": m.created_at,
            "response_status": m.response_status,
            "finish_reason": m.finish_reason,
        } for m in messages
    ]

from services.qdrant_service import delete_memory_by_session

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    """Delete a session and memory whose only evidence is that session."""
    
    # 1. Hapus dari SQLite (UI History)
    conv = db.query(Conversation).filter(Conversation.id == session_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found")
        
    source_message_ids = [message.id for message in conv.messages]

    # Persist cancellation before touching external stores so a background
    # worker cannot recreate graph/vector memory during session deletion.
    conv.deleted_at = conv.deleted_at or datetime.now(timezone.utc)
    conv.active_turn_id = None
    conv.active_turn_expires_at = None
    conv.is_pinned = False
    conv.pinned_at = None
    memory_service.cancel_memory_jobs_for_conversation(session_id, db)
    db.commit()

    try:
        # External deletion is intentionally completed before SQLite history is
        # removed. If it fails, the user can retry and provenance remains
        # available instead of silently becoming dangling evidence.
        graph_cleanup = neo4j_client.remove_conversation_provenance(
            session_id,
            source_message_ids,
        )
        # Run vector deletion last. A worker which was already inside an
        # in-flight upsert when cancellation was committed is then still
        # covered by this final session-wide delete.
        delete_memory_by_session(session_id)
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fully delete session %s", session_id)
        raise HTTPException(
            status_code=502,
            detail="Session is tombstoned, but external memory cleanup failed and must be retried",
        ) from exc

    db.query(Message).filter(Message.conversation_id == session_id).delete()
    from models.memory_outbox import MemoryOutbox
    db.query(MemoryOutbox).filter(MemoryOutbox.conversation_id == session_id).delete()
    conv.title = "Deleted session"
    conv.summary = None
    conv.summary_pending = False
    conv.project_id = None
    db.commit()
    
    return {"message": "Session and derived memory deleted successfully", "graph_cleanup": graph_cleanup}

from services.neo4j_service import neo4j_client

@router.get("/memory/graph")
def get_knowledge_graph(limit: int = Query(300, ge=1, le=1000), include_inactive: bool = False):
    """Mendapatkan data nodes dan edges dari Neo4j untuk visualisasi 2D"""
    return neo4j_client.get_graph_data(limit=limit, include_inactive=include_inactive)


def _model_updates(request_model) -> dict:
    if hasattr(request_model, "model_dump"):
        return request_model.model_dump(exclude_unset=True)
    return request_model.dict(exclude_unset=True)


@router.delete("/memory/graph/node/{entity_key}")
def delete_graph_node(entity_key: str):
    """Hapus satu entity secara presisi beserta relasinya."""
    deleted = neo4j_client.delete_node(entity_key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return {"message": "Graph node deleted", "deleted": deleted}


@router.patch("/memory/graph/node/{entity_key}")
def update_graph_node(entity_key: str, request: GraphNodeUpdate):
    """Koreksi nama, konteks identitas, atau importance satu entity."""
    try:
        updated = neo4j_client.update_node(entity_key, _model_updates(request))
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return updated


@router.delete("/memory/graph/fact/{fact_id}")
def delete_graph_fact(fact_id: str):
    """Hapus satu fakta/edge tanpa menghapus entity di kedua ujungnya."""
    deleted = neo4j_client.delete_fact(fact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Graph fact not found")
    from services.qdrant_service import set_memories_status
    source_ids = deleted.get("source_message_ids") or []
    memory_service.set_source_messages_memory_status(source_ids, "inactive")
    set_memories_status(source_ids, status="inactive")
    return {"message": "Graph fact deleted", "deleted": deleted}


@router.patch("/memory/graph/fact/{fact_id}")
def update_graph_fact(fact_id: str, request: GraphFactUpdate):
    """Aktif/nonaktifkan atau koreksi importance satu fakta."""
    try:
        updated = neo4j_client.update_fact(fact_id, _model_updates(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Graph fact not found")
    if request.is_current is not None:
        from services.qdrant_service import set_memories_status
        source_ids = updated.get("source_message_ids") or []
        memory_service.set_source_messages_memory_status(
            source_ids, "active" if request.is_current else "inactive"
        )
        set_memories_status(
            source_ids,
            status="active" if request.is_current else "inactive",
        )
    return updated


@router.get("/memory/jobs")
def get_memory_jobs(limit: int = Query(50, ge=1, le=100)):
    """Inspect durable memory jobs without returning their chat payload."""
    return {"jobs": memory_service.list_memory_jobs(limit=limit)}


@router.post("/memory/jobs/{job_id}/retry")
def retry_memory_job(job_id: str, background_tasks: BackgroundTasks):
    """Retry an unfinished memory job from its durable SQLite source event."""
    try:
        job = memory_service.retry_memory_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="Memory job not found")
    background_tasks.add_task(memory_service.process_memory_job, job_id)
    return {"message": "Memory job retry scheduled", "job": job}

from sqlalchemy import func
from models.llm_usage import LLMUsageLog
from models.ai_invocation import AIInvocation
from services.qdrant_service import get_stats as get_qdrant_stats

@router.get("/system/stats")
def get_system_stats(db: Session = Depends(get_db)):
    """Mendapatkan statistik sistem dari seluruh database"""
    # SQLite Stats
    total_sessions = db.query(Conversation).count()
    total_messages = db.query(Message).count()
    
    # Token Usage
    total_tokens = db.query(func.sum(LLMUsageLog.prompt_tokens + LLMUsageLog.completion_tokens)).scalar() or 0
    total_tokens += db.query(func.sum(AIInvocation.total_tokens)).scalar() or 0
    invocation_count = db.query(AIInvocation).count()
    unknown_usage_calls = db.query(AIInvocation).filter(AIInvocation.total_tokens.is_(None)).count()
    
    # Graph & Vector Stats
    graph_stats = neo4j_client.get_stats()
    vector_stats = get_qdrant_stats()
    
    return {
        "sessions": total_sessions,
        "messages": total_messages,
        "tokens": total_tokens,
        "ai_invocations": invocation_count,
        "ai_invocations_unknown_usage": unknown_usage_calls,
        "graph_nodes": graph_stats.get("nodes", 0),
        "graph_edges": graph_stats.get("edges", 0),
        "vector_memories": vector_stats.get("vectors", 0)
    }
