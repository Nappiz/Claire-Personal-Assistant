from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from schemas.chat_sch import ChatRequest, ChatResponse, ConversationPinUpdate, ProjectCreate, ProjectUpdate, GraphNodeUpdate, GraphFactUpdate
from app.application.errors import ApplicationError
from app.api.dependencies import get_db, resource_dependencies, chat_dependencies
from app.application.projects import operations as workflows

router = APIRouter()

@router.get("/projects")
def get_projects(db: Any = Depends(get_db)):
    try:
        return workflows.get_projects(resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects", status_code=201)
def create_project(request: ProjectCreate, db: Any = Depends(get_db)):
    try:
        return workflows.create_project(request, resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    request: ProjectUpdate,
    db: Any = Depends(get_db),
):
    try:
        return workflows.update_project(project_id, request, resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Any = Depends(get_db)):
    try:
        return workflows.delete_project(project_id, resource_dependencies(db))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
