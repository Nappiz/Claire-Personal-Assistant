"""Exercise the actual normalized/tracked planner stream with isolated telemetry."""
from types import SimpleNamespace as Record
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.infrastructure.llm.openai_gateway import OpenAICompletionGateway
from app.observability import ai_telemetry
from schemas.chat_sch import MemoryContext
from test_chat_planning_stream import ControlledStream, chunk
from test_llm_workflow_boundaries import fake_workflows


class ChatPlanningStreamTelemetryTests(IsolatedAsyncioTestCase):
    async def test_real_gateway_preserves_terminal_telemetry_for_planner_stream(self):
        for expected in ("success", "incomplete", "cancelled", "failed"):
            with self.subTest(status=expected):
                stream = ControlledStream([
                    chunk("first"),
                    chunk(" rest", finish="length" if expected == "incomplete" else "stop",
                          usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}),
                ], error=RuntimeError("broken") if expected == "failed" else None)
                client = Record(close=AsyncMock(), chat=Record(completions=Record(
                    create=AsyncMock(return_value=stream))))
                gateway = OpenAICompletionGateway(Record())
                with patch.object(gateway, "get_llm_connection", return_value=("offline", None)), patch.object(
                    gateway, "create_async_llm_client", return_value=client
                ), patch.object(ai_telemetry, "_persist") as persist:
                    response = fake_workflows(gateway).generate_chat_response_stream(
                        "Jelaskan recursion", MemoryContext())
                    try:
                        self.assertEqual("first", (await anext(response))["delta"])
                        if expected == "failed":
                            with self.assertRaisesRegex(RuntimeError, "broken"):
                                _ = [event async for event in response]
                        elif expected != "cancelled":
                            events = [event async for event in response]
                            usage = next(event["usage"] for event in events if event["type"] == "usage")
                            self.assertEqual(12, usage["total_tokens"])
                            self.assertEqual(1, len(usage["invocation_ids"]))
                    finally:
                        await response.aclose()
                    self.assertEqual(expected, persist.call_args.args[1]["status"])
                    self.assertEqual(1, client.chat.completions.create.await_count)
                    self.assertTrue(client.chat.completions.create.call_args.kwargs["stream"])
                    self.assertTrue(stream.closed)
                    client.close.assert_awaited_once()
