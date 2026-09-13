import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import router as chat_routes
from app.api.routers import settings as settings_routes
from app.observability.correlation import CorrelationMiddleware
from app.observability.log_buffer import log_buffer, configure_logging
from app.infrastructure.persistence.legacy_schema import ensure_local_legacy_schema as repair_schema
from app.infrastructure.runtime import create_worker_tasks
from app.workers.maintenance_worker import memory_maintenance_task
from app.workers.memory_outbox_worker import memory_outbox_retry_task
from configs.database import engine
from models import Base

configure_logging()
logger = logging.getLogger(__name__)


def ensure_local_legacy_schema():
    repair_schema(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_local_legacy_schema()
    tasks = create_worker_tasks(logger)
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

app = FastAPI(title="Claire AI", lifespan=lifespan)
app.add_middleware(CorrelationMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3100"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_routes.router, prefix="/api/v1")
app.include_router(settings_routes.router, prefix="/api/v1")

@app.get("/api/v1/logs")
def read_logs():
    return {"logs": "\n".join(log_buffer)}

@app.get("/")
def read_root():
    return {"message": "Welcome to Claire AI Backend"}
