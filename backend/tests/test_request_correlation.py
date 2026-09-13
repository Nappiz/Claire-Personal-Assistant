import asyncio
import logging
from unittest import IsolatedAsyncioTestCase

from app.observability.correlation import CorrelationMiddleware, CorrelationFilter, correlation


class RequestCorrelationTests(IsolatedAsyncioTestCase):
    async def test_concurrent_requests_keep_distinct_context_and_reset_afterward(self):
        observed = []

        async def application(scope, _receive, _send):
            await asyncio.sleep(0)
            observed.append((scope["state"]["request_id"], correlation.get()["request_id"]))

        middleware = CorrelationMiddleware(application)
        await asyncio.gather(*(
            middleware({"type": "http", "headers": [(b"x-request-id", request_id.encode())]}, None, None)
            for request_id in ("request-a", "request-b")
        ))
        self.assertEqual([("request-a", "request-a"), ("request-b", "request-b")], sorted(observed))
        self.assertEqual({}, correlation.get())

    async def test_request_failure_resets_context_and_filter_has_safe_defaults(self):
        async def failing_application(_scope, _receive, _send):
            raise RuntimeError("request failed")

        with self.assertRaises(RuntimeError):
            await CorrelationMiddleware(failing_application)({"type": "http", "headers": []}, None, None)
        self.assertEqual({}, correlation.get())
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
        self.assertTrue(CorrelationFilter().filter(record))
        self.assertEqual(("-", "-", "-"), (record.request_id, record.session_id, record.turn_id))
