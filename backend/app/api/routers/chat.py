from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from schemas.chat_sch import ChatRequest, ChatResponse, ConversationPinUpdate, ProjectCreate, ProjectUpdate, GraphNodeUpdate, GraphFactUpdate
from app.application.errors import ApplicationError
from app.api.dependencies import get_db, resource_dependencies, chat_dependencies
from app.application.chat.complete_turn import chat_endpoint as complete_turn
from app.application.chat.stream_turn import stream_chat_endpoint as stream_turn
from app.api.sse import encode_events, STREAM_HEADERS

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Any = Depends(get_db),
):
    """Run one durable, idempotent chat turn."""
    try:
        result = await complete_turn(request, background_tasks, chat_dependencies(db))
        return result
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/chat/stream")
async def stream_chat_endpoint(
    request: ChatRequest,
    client_request: Request,
    background_tasks: BackgroundTasks,
):
    """Stream an OpenAI-compatible chat completion to the browser as SSE."""
    try:
        result = await stream_turn(request, client_request, background_tasks, chat_dependencies(None))
        return StreamingResponse(encode_events(result), media_type='text/event-stream', headers=STREAM_HEADERS)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
