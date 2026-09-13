"""Preserved background loop with injected operations."""
import asyncio
import logging

async def conversation_summary_retry_task(operation, logger=None):
    logger = logger or logging.getLogger('main')
    while True:
        try:

            await asyncio.to_thread(operation, limit=20)
        except Exception:
            logger.exception("Conversation summary retry task failed")
        await asyncio.sleep(60)
