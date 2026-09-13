from fastapi import APIRouter
from .routers import chat, conversations, projects, graph, memory, system
router = APIRouter()
for resource in (chat, conversations, projects, graph, memory, system):
    router.include_router(resource.router)
