"""Production composition for independently testable in-process workers."""
import asyncio
from configs.database import SessionLocal
from app.infrastructure.persistence.settings import SQLAlchemySettingsRepository
from app.infrastructure.graph.neo4j_graph_store import graph_store
from app.infrastructure.vector.qdrant_vector_store import vector_store
from app.infrastructure.memory.composition import memory_workflows
from app.application.memory.run_maintenance import run_memory_maintenance_once
from app.workers.maintenance_worker import memory_maintenance_task
from app.workers.memory_outbox_worker import memory_outbox_retry_task
from app.workers.summary_worker import conversation_summary_retry_task
from app.workers.vector_reindex_worker import vector_memory_reindex_task


def create_worker_tasks(logger):
    def maintenance():
        return run_memory_maintenance_once(
            SessionLocal, lambda db, key: SQLAlchemySettingsRepository(db).get(key),
            lambda db, key, value: SQLAlchemySettingsRepository(db).set(key, value),
            graph_store, logger)
    return [
        asyncio.create_task(memory_maintenance_task(maintenance, logger)),
        asyncio.create_task(memory_outbox_retry_task(memory_workflows.process_due_memory_jobs, logger)),
        asyncio.create_task(conversation_summary_retry_task(memory_workflows.process_due_summaries, logger)),
        asyncio.create_task(vector_memory_reindex_task(
            memory_workflows.reindex_vector_memory_from_outbox,
            vector_store.warmup_embedding_model, logger)),
    ]
