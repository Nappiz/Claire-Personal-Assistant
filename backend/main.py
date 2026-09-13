import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import inspect, text
from app.api import router as chat_routes
from app.api.routers import settings as settings_routes
from fastapi.middleware.cors import CORSMiddleware
from services.neo4j_service import neo4j_client
from services.settings_service import get_setting, set_setting
from configs.database import SessionLocal, engine
from models import Base
from datetime import datetime, timezone
from app.observability.correlation import CorrelationFilter, CorrelationMiddleware

from collections import deque
import logging

# In-memory log buffer
log_buffer = deque(maxlen=1000)

class MemoryHandler(logging.Handler):
    def emit(self, record):
        log_buffer.append(self.format(record))

memory_handler = MemoryHandler()
memory_handler.addFilter(CorrelationFilter())
memory_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s request=%(request_id)s session=%(session_id)s turn=%(turn_id)s: %(message)s"))
logging.getLogger().addHandler(memory_handler)
logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger(__name__)


def ensure_local_legacy_schema() -> None:
    """Upgrade legacy local SQLite databases created before Alembic tracking."""
    if engine.dialect.name != "sqlite":
        return
    message_columns = {column["name"] for column in inspect(engine).get_columns("messages")}
    conversation_columns = {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }
    outbox_columns = {
        column["name"] for column in inspect(engine).get_columns("memory_outbox")
    }
    with engine.begin() as connection:
        if "message_type" not in message_columns:
            connection.execute(
                text(
                    "ALTER TABLE messages ADD COLUMN message_type "
                    "VARCHAR(30) NOT NULL DEFAULT 'normal'"
                )
            )
        if "error_details" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN error_details JSON"))
        if "turn_id" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN turn_id VARCHAR(36)"))
        if "turn_sequence" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN turn_sequence INTEGER"))
        if "response_status" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN response_status VARCHAR(20) NOT NULL DEFAULT 'complete'"))
        if "finish_reason" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN finish_reason VARCHAR(50)"))
        if "memory_status" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN memory_status VARCHAR(20) NOT NULL DEFAULT 'active'"))
        if "is_pinned" not in conversation_columns:
            connection.execute(
                text(
                    "ALTER TABLE conversations ADD COLUMN is_pinned "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "pinned_at" not in conversation_columns:
            connection.execute(
                text("ALTER TABLE conversations ADD COLUMN pinned_at DATETIME")
            )
        if "project_id" not in conversation_columns:
            connection.execute(
                text("ALTER TABLE conversations ADD COLUMN project_id VARCHAR(36)")
            )
        for column_name, definition in (
            ("summary_version", "INTEGER NOT NULL DEFAULT 0"),
            ("summary_through_sequence", "INTEGER NOT NULL DEFAULT 0"),
            ("summary_pending", "BOOLEAN NOT NULL DEFAULT 0"),
            ("next_turn_sequence", "INTEGER NOT NULL DEFAULT 1"),
            ("active_turn_id", "VARCHAR(36)"),
            ("active_turn_expires_at", "DATETIME"),
            ("deleted_at", "DATETIME"),
        ):
            if column_name not in conversation_columns:
                connection.execute(text(f"ALTER TABLE conversations ADD COLUMN {column_name} {definition}"))
        if "project_id" not in outbox_columns:
            connection.execute(
                text("ALTER TABLE memory_outbox ADD COLUMN project_id VARCHAR(36)")
            )
        if "project_name" not in outbox_columns:
            connection.execute(
                text("ALTER TABLE memory_outbox ADD COLUMN project_name VARCHAR(120)")
            )
        if "scope" not in outbox_columns:
            connection.execute(
                text(
                    "ALTER TABLE memory_outbox ADD COLUMN scope "
                    "VARCHAR(20) NOT NULL DEFAULT 'global'"
                )
            )
        for column_name, definition in (
            ("lease_token", "VARCHAR(36)"),
            ("lease_expires_at", "DATETIME"),
            ("event_at", "DATETIME"),
        ):
            if column_name not in outbox_columns:
                connection.execute(text(f"ALTER TABLE memory_outbox ADD COLUMN {column_name} {definition}"))
        connection.execute(text("UPDATE memory_outbox SET event_at = created_at WHERE event_at IS NULL"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_conversations_project_id "
                "ON conversations (project_id)"
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_turn_id ON messages (turn_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_turn_sequence ON messages (turn_sequence)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_memory_status ON messages (memory_status)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_message_turn_role ON messages (conversation_id, turn_id, role)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_active_turn_id ON conversations (active_turn_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_active_turn_expires_at ON conversations (active_turn_expires_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_deleted_at ON conversations (deleted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_outbox_lease_token ON memory_outbox (lease_token)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_outbox_lease_expires_at ON memory_outbox (lease_expires_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_outbox_event_at ON memory_outbox (event_at)"))

        legacy_rows = connection.execute(
            # SQLite rowid preserves legacy insertion order when timestamps tie;
            # UUID lexical order is unrelated to conversation chronology.
            text("SELECT id, conversation_id, role FROM messages WHERE turn_sequence IS NULL ORDER BY conversation_id, created_at, rowid")
        ).fetchall()
        counters: dict[str, int] = {}
        roles_in_turn: dict[str, int] = {}
        for message_id, conversation_id, role in legacy_rows:
            current = counters.get(conversation_id, 1)
            position = roles_in_turn.get(conversation_id, 0)
            # A second user starts another turn, rather than becoming the
            # presumed assistant half of a blind two-row pairing.
            if role == "user" and position:
                current += 1
                position = 0
            connection.execute(
                text("UPDATE messages SET turn_sequence = :sequence WHERE id = :message_id"),
                {"sequence": current, "message_id": message_id},
            )
            if role == "assistant":
                counters[conversation_id] = current + 1
                roles_in_turn[conversation_id] = 0
            else:
                counters[conversation_id] = current
                roles_in_turn[conversation_id] = 1
        for conversation_id, next_sequence in counters.items():
            connection.execute(
                text("UPDATE conversations SET next_turn_sequence = MAX(next_turn_sequence, :next_sequence) WHERE id = :conversation_id"),
                {"next_sequence": next_sequence + (1 if roles_in_turn.get(conversation_id) else 0), "conversation_id": conversation_id},
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_memory_outbox_project_id "
                "ON memory_outbox (project_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_memory_outbox_scope "
                "ON memory_outbox (scope)"
            )
        )


def _run_memory_maintenance_once() -> None:
    db = SessionLocal()
    try:
        last_run_str = get_setting(db, "last_consolidation_time")
        now = datetime.now(timezone.utc)
        if last_run_str:
            last_run = datetime.fromisoformat(last_run_str)
            time_diff = (now - last_run).total_seconds()
            if time_diff < 86400:
                return
            days_passed = time_diff / 86400.0
        else:
            days_passed = 1.0
        logger.info("Running scheduled memory consolidation (days=%s)", days_passed)
        neo4j_client.consolidate_memory(days_passed=days_passed)
        set_setting(db, "last_consolidation_time", now.isoformat())
    finally:
        db.close()


async def memory_maintenance_task():
    """Background task mengecek setiap 1 jam, menggunakan real-time diff."""
    while True:
        try:
            await asyncio.to_thread(_run_memory_maintenance_once)
        except Exception as e:
            logger.error(f"Maintenance task error: {e}")
            
        # Cek lagi setiap 1 jam (3600 detik)
        await asyncio.sleep(3600)


async def memory_outbox_retry_task():
    """Retry failed external-memory writes independently of scheduled decay."""
    while True:
        try:
            from services.memory_service import process_due_memory_jobs

            completed = await asyncio.to_thread(process_due_memory_jobs, limit=25)
            if completed:
                logger.info("Processed %s due memory outbox job(s)", len(completed))
        except Exception:
            logger.exception("Memory outbox retry task failed")
        await asyncio.sleep(60)


async def conversation_summary_retry_task():
    while True:
        try:
            from services.memory_service import process_due_summaries

            await asyncio.to_thread(process_due_summaries, limit=20)
        except Exception:
            logger.exception("Conversation summary retry task failed")
        await asyncio.sleep(60)


async def vector_memory_reindex_task():
    """Migrate legacy vector payloads without delaying API readiness."""
    try:
        from services.memory_service import reindex_vector_memory_from_outbox
        from services.qdrant_service import warmup_embedding_model

        result = await asyncio.to_thread(reindex_vector_memory_from_outbox)
        logger.info("Vector-memory reindex result: %s", result)
        health = await asyncio.to_thread(warmup_embedding_model)
        logger.info("Embedding warmup result: %s", health)
    except Exception:
        logger.exception("Vector-memory reindex failed; chat will run in degraded mode")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create SQLite tables if they don't exist
    Base.metadata.create_all(bind=engine)
    ensure_local_legacy_schema()

    # Startup: Start background task
    task = asyncio.create_task(memory_maintenance_task())
    outbox_task = asyncio.create_task(memory_outbox_retry_task())
    summary_task = asyncio.create_task(conversation_summary_retry_task())
    reindex_task = asyncio.create_task(vector_memory_reindex_task())
    yield
    # Shutdown: Cancel the task
    task.cancel()
    outbox_task.cancel()
    summary_task.cancel()
    reindex_task.cancel()

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
