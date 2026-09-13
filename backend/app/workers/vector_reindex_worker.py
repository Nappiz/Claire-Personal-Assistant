"""Preserved background loop with injected operations."""
import asyncio
import logging

async def vector_memory_reindex_task(operation, warmup, logger=None):
    """Migrate legacy vector payloads without delaying API readiness."""
    logger = logger or logging.getLogger('main')
    try:

        result = await asyncio.to_thread(operation)
        logger.info("Vector-memory reindex result: %s", result)
        health = await asyncio.to_thread(warmup)
        logger.info("Embedding warmup result: %s", health)
    except Exception:
        logger.exception("Vector-memory reindex failed; chat will run in degraded mode")
