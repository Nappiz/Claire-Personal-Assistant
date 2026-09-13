from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from schemas.chat_sch import ChatRequest, ChatResponse, ConversationPinUpdate, ProjectCreate, ProjectUpdate, GraphNodeUpdate, GraphFactUpdate
from app.application.errors import ApplicationError
from app.api.dependencies import get_db, resource_dependencies, chat_dependencies
from app.application.graph import operations as workflows

router = APIRouter()

@router.get("/memory/graph")
def get_knowledge_graph(limit: int = Query(300, ge=1, le=1000), include_inactive: bool = False):
    """Mendapatkan data nodes dan edges dari Neo4j untuk visualisasi 2D"""
    try:
        return workflows.get_knowledge_graph(limit, include_inactive, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete("/memory/graph/node/{entity_key}")
def delete_graph_node(entity_key: str):
    """Hapus satu entity secara presisi beserta relasinya."""
    try:
        return workflows.delete_graph_node(entity_key, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/memory/graph/node/{entity_key}")
def update_graph_node(entity_key: str, request: GraphNodeUpdate):
    """Koreksi nama, konteks identitas, atau importance satu entity."""
    try:
        return workflows.update_graph_node(entity_key, request, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.delete("/memory/graph/fact/{fact_id}")
def delete_graph_fact(fact_id: str):
    """Hapus satu fakta/edge tanpa menghapus entity di kedua ujungnya."""
    try:
        return workflows.delete_graph_fact(fact_id, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/memory/graph/fact/{fact_id}")
def update_graph_fact(fact_id: str, request: GraphFactUpdate):
    """Aktif/nonaktifkan atau koreksi importance satu fakta."""
    try:
        return workflows.update_graph_fact(fact_id, request, resource_dependencies(None))
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
