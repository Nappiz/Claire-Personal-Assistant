from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from schemas.chat_sch import ChatRequest, ChatResponse, ConversationPinUpdate, ProjectCreate, ProjectUpdate, GraphNodeUpdate, GraphFactUpdate
from app.application.errors import ApplicationError
from app.api.dependencies import get_db, resource_dependencies, chat_dependencies
from app.application.conversations import operations as workflows

router = APIRouter()

@router.get("/sessions")
def get_sessions(db: Any = Depends(get_db)):
    """Mendapatkan daftar semua sesi obrolan (terbaru di atas)"""
    try:
        return workflows.get_sessions(resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/sessions/{session_id}/pin")
def set_session_pin(
    session_id: str,
    request: ConversationPinUpdate,
    db: Any = Depends(get_db),
):
    """Pin or unpin a conversation in the history sidebar."""
    try:
        return workflows.set_session_pin(session_id, request, resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/history/{session_id}")
def get_history(session_id: str, db: Any = Depends(get_db)):
    """Mendapatkan riwayat obrolan lengkap dari sesi tertentu"""
    try:
        return workflows.get_history(session_id, resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Any = Depends(get_db)):
    """Delete a session and memory whose only evidence is that session."""
    try:
        return workflows.delete_session(session_id, resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
