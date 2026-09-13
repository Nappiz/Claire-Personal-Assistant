"""Worker contracts without application startup, stores, or wall-clock sleeps."""
import asyncio
import unittest
from unittest.mock import Mock, patch, AsyncMock
from app.workers.maintenance_worker import memory_maintenance_task
from app.workers.memory_outbox_worker import memory_outbox_retry_task
from app.workers.summary_worker import conversation_summary_retry_task
from app.workers.vector_reindex_worker import vector_memory_reindex_task
from app.application.memory.run_maintenance import run_memory_maintenance_once


class WorkerContracts(unittest.IsolatedAsyncioTestCase):
    async def check_loop(self, worker, operation, interval, kwargs):
        async def stop(seconds):
            self.assertEqual(seconds, interval)
            raise asyncio.CancelledError()
        with patch("asyncio.sleep", side_effect=stop):
            with self.assertRaises(asyncio.CancelledError):
                await worker(operation, Mock())
        operation.assert_called_once_with(**kwargs)

    async def test_outbox_limit_interval(self):
        await self.check_loop(memory_outbox_retry_task, Mock(return_value=[]), 60, {"limit":25})

    async def test_summary_limit_interval(self):
        await self.check_loop(conversation_summary_retry_task, Mock(), 60, {"limit":20})

    async def test_maintenance_failure_keeps_retry_interval(self):
        await self.check_loop(memory_maintenance_task, Mock(side_effect=RuntimeError("offline")), 3600, {})

    async def test_reindex_before_warmup(self):
        sequence = []
        await vector_memory_reindex_task(lambda: sequence.append("reindex"), lambda: sequence.append("warmup"), Mock())
        self.assertEqual(sequence, ["reindex","warmup"])

    async def test_reindex_failure_does_not_warmup(self):
        warmup = Mock()
        await vector_memory_reindex_task(Mock(side_effect=RuntimeError("offline")), warmup, Mock())
        warmup.assert_not_called()

    async def test_lifespan_cancels_workers_even_on_request_failure(self):
        import main
        cleaned = []
        async def worker():
            try:
                await asyncio.Future()
            finally:
                cleaned.append(True)
        tasks = [asyncio.create_task(worker()) for _ in range(4)]
        await asyncio.sleep(0)
        with patch.object(main.Base.metadata,"create_all"), patch.object(main,"ensure_local_legacy_schema"), patch.object(main,"create_worker_tasks", return_value=tasks):
            with self.assertRaises(RuntimeError):
                async with main.lifespan(main.app):
                    raise RuntimeError("request failure")
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertEqual(len(cleaned),4)


class MaintenanceContracts(unittest.TestCase):
    def test_recent_run_closes_database_without_consolidation(self):
        from datetime import datetime, timezone
        db, graph, save = Mock(), Mock(), Mock()
        run_memory_maintenance_once(lambda:db, lambda *args:datetime.now(timezone.utc).isoformat(), save, graph, Mock())
        db.close.assert_called_once_with()
        graph.consolidate_memory.assert_not_called()
        save.assert_not_called()
