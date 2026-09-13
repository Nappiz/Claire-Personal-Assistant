"""Preserved background loop with injected operations."""
import asyncio
import logging

async def memory_maintenance_task(operation, logger=None):
    """Background task mengecek setiap 1 jam, menggunakan real-time diff."""
    logger = logger or logging.getLogger('main')
    while True:
        try:
            await asyncio.to_thread(operation)
        except Exception as e:
            logger.error(f"Maintenance task error: {e}")

        # Cek lagi setiap 1 jam (3600 detik)
        await asyncio.sleep(3600)
