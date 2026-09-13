from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from schemas.chat_sch import ChatRequest, ChatResponse, ConversationPinUpdate, ProjectCreate, ProjectUpdate, GraphNodeUpdate, GraphFactUpdate
from app.application.errors import ApplicationError
from app.api.dependencies import get_db, resource_dependencies, chat_dependencies
from app.application.system import stats as workflows

router = APIRouter()

@router.get("/system/stats")
def get_system_stats(db: Any = Depends(get_db)):
    """Mendapatkan statistik sistem dari seluruh database"""
    try:
        return workflows.get_system_stats(resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
