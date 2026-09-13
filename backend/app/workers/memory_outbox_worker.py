"""Preserved background loop with injected operations."""
import asyncio
import logging

async def memory_outbox_retry_task(operation, logger=None):
    """Retry failed external-memory writes independently of scheduled decay."""
    logger = logger or logging.getLogger('main')
    while True:
        try:

            completed = await asyncio.to_thread(operation, limit=25)
            if completed:
                logger.info("Processed %s due memory outbox job(s)", len(completed))
        except Exception:
            logger.exception("Memory outbox retry task failed")
        await asyncio.sleep(60)
