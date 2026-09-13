from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from schemas.chat_sch import ChatRequest, ChatResponse, ConversationPinUpdate, ProjectCreate, ProjectUpdate, GraphNodeUpdate, GraphFactUpdate
from app.application.errors import ApplicationError
from app.api.dependencies import get_db, resource_dependencies, chat_dependencies
from app.application.memory import operations as workflows

router = APIRouter()

@router.get("/memory/jobs")
def get_memory_jobs(limit: int = Query(50, ge=1, le=100)):
    """Inspect durable memory jobs without returning their chat payload."""
    try:
        return workflows.get_memory_jobs(limit, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/memory/jobs/{job_id}/retry")
def retry_memory_job(job_id: str, background_tasks: BackgroundTasks):
    """Retry an unfinished memory job from its durable SQLite source event."""
    try:
        return workflows.retry_memory_job(job_id, background_tasks, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
