"""Planner must stream genuine provider deltas, not replay a buffered answer."""
import asyncio
from types import SimpleNamespace as Record
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from openai.types.chat import ChatCompletionChunk

from app.domain.llm.planning_stream import PlanningStreamResult
from app.infrastructure.llm.provider_serializers import ProviderSerializers
from schemas.chat_sch import MemoryContext, WebPageContent, WebSearchContext, WebSearchResult
from test_llm_workflow_boundaries import fake_workflows


def chunk(text=None, *, tools=None, finish=None, usage=None, **extensions):
    return ChatCompletionChunk.model_validate({
        "id": "completion-1", "object": "chat.completion.chunk",
        "created": 1, "model": "test-model", "usage": usage,
        "choices": [{"index": 0, "finish_reason": finish,
                     "delta": {"content": text, "tool_calls": tools, **extensions}}],
    })


class ControlledStream:
    def __init__(self, chunks, *, gate=None, error=None):
        self.chunks = iter(chunks)
        self.gate, self.error = gate, error
        self.read_count = 0
        self.closed = False
        self.exhausted = False
        self.waiting = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.read_count == 1 and self.gate is not None:
            self.waiting.set()
            await self.gate.wait()
        try:
            result = next(self.chunks)
        except StopIteration:
            self.exhausted = True
            if self.error is not None:
                raise self.error
            raise StopAsyncIteration
        self.read_count += 1
        return result


def setup_workflow(*streams):
    gateway = Mock()
    gateway.get_llm_connection.return_value = ("fake", None)
    client = Record(close=AsyncMock())
    gateway.create_async_llm_client.return_value = client
    gateway.tracked_async_completion = AsyncMock(
        side_effect=[(stream, f"call-{index}") for index, stream in enumerate(streams)])
    return fake_workflows(gateway), gateway, client


class ChatPlanningStreamTests(IsolatedAsyncioTestCase):
    async def test_first_delta_arrives_before_provider_finishes_using_one_call(self):
        gate = asyncio.Event()
        stream = ControlledStream([chunk("satu"), chunk(" "), chunk("dua", finish="stop")], gate=gate)
        workflows, gateway, client = setup_workflow(stream)
        response = workflows.generate_chat_response_stream("Jelaskan recursion", MemoryContext())
        try:
            first = await asyncio.wait_for(anext(response), timeout=1)
            self.assertEqual({"type": "delta", "delta": "satu"}, first)
            self.assertFalse(stream.exhausted)
            self.assertEqual(1, gateway.tracked_async_completion.await_count)
            request = gateway.tracked_async_completion.call_args.kwargs
            self.assertTrue(request["stream"])
            self.assertEqual({"include_usage": True}, request["stream_options"])
            self.assertEqual(0.0, request["temperature"])
            self.assertEqual("auto", request["tool_choice"])
            gate.set()
            remaining = [event async for event in response]
            self.assertEqual("satu dua", first["delta"] + "".join(
                event["delta"] for event in remaining if event["type"] == "delta"))
            self.assertEqual("complete", remaining[-1]["response_status"])
        finally:
            gate.set()
            await response.aclose()
        self.assertTrue(stream.closed)
        client.close.assert_awaited_once()

    async def test_cumulative_usage_is_counted_once_and_length_is_incomplete(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
        stream = ControlledStream([
            chunk("  satu"), chunk("\n", usage=usage),
            chunk("dua  ", finish="length", usage=usage),
            Record(choices=[], usage=Record(**usage)),
        ])
        workflows, gateway, _ = setup_workflow(stream)
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan recursion", MemoryContext())]
        self.assertEqual("  satu\ndua  ", "".join(
            event["delta"] for event in events if event["type"] == "delta"))
        total = next(event["usage"] for event in events if event["type"] == "usage")
        self.assertEqual(12, total["total_tokens"])
        self.assertEqual(["call-0"], total["invocation_ids"])
        self.assertEqual("incomplete", events[-1]["response_status"])
        self.assertEqual("length", events[-1]["finish_reason"])
        self.assertEqual(1, gateway.tracked_async_completion.await_count)

    async def test_disconnect_closes_planner_stream_and_client_without_regeneration(self):
        stream = ControlledStream([chunk("partial"), chunk("rest", finish="stop")])
        workflows, gateway, client = setup_workflow(stream)
        response = workflows.generate_chat_response_stream("Jelaskan recursion", MemoryContext())
        try:
            self.assertEqual("partial", (await anext(response))["delta"])
        finally:
            await response.aclose()
        self.assertTrue(stream.closed)
        self.assertFalse(stream.exhausted)
        self.assertEqual(1, gateway.tracked_async_completion.await_count)
        client.close.assert_awaited_once()

    async def test_cancellation_while_waiting_closes_stream_and_client(self):
        gate = asyncio.Event()
        stream = ControlledStream([chunk("partial"), chunk("rest")], gate=gate)
        workflows, gateway, client = setup_workflow(stream)
        response = workflows.generate_chat_response_stream("Jelaskan recursion", MemoryContext())
        await anext(response)
        pending = asyncio.create_task(anext(response))
        try:
            await asyncio.wait_for(stream.waiting.wait(), timeout=1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        finally:
            pending.cancel()
            await response.aclose()
        self.assertTrue(stream.closed)
        self.assertEqual(1, gateway.tracked_async_completion.await_count)
        client.close.assert_awaited_once()

    async def test_error_after_visible_text_does_not_append_a_second_answer(self):
        stream = ControlledStream([chunk("partial")], error=RuntimeError("stream broke"))
        workflows, gateway, client = setup_workflow(stream)
        response = workflows.generate_chat_response_stream("Jelaskan recursion", MemoryContext())
        try:
            self.assertEqual("partial", (await anext(response))["delta"])
            with self.assertRaisesRegex(RuntimeError, "stream broke"):
                await anext(response)
        finally:
            await response.aclose()
        self.assertTrue(stream.closed)
        self.assertEqual(1, gateway.tracked_async_completion.await_count)
        client.close.assert_awaited_once()

    async def test_fragmented_read_calls_wait_for_completion_and_replay_metadata(self):
        urls = ["https://example.com/one", "https://example.com/two"]
        signature = {"google": {"thought_signature": "opaque+/=="}}
        planning = ControlledStream([
            chunk(tools=[{"index": index, "id": f"read-{index}", "type": "function",
                          "function": {"name": "read_", "arguments": '{"url":"'}}
                         for index in (1, 0)], reasoning_content="PRIVATE"),
            chunk(tools=[{"index": index, "function": {"name": "url",
                          "arguments": urls[index] + '"}'}, "extra_content": signature}
                         for index in (0, 1)], finish="tool_calls",
                  extra_content={"provider": {"opaque": "message-signature"}}),
            Record(choices=[], usage=Record(prompt_tokens=10, completion_tokens=2, total_tokens=12)),
        ])
        final = ControlledStream([chunk("final", finish="stop",
            usage={"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21})])
        workflows, gateway, client = setup_workflow(planning, final)
        serializers = ProviderSerializers()
        gateway.serialized_assistant_tool_message.side_effect = serializers.serialized_assistant_tool_message
        workflows.web.normalize_public_url.side_effect = lambda value: value

        async def read(url, **kwargs):
            self.assertTrue(planning.exhausted)
            self.assertTrue(planning.closed)
            return WebPageContent(url=url, content="evidence")

        workflows.web.read_url = AsyncMock(side_effect=read)
        context = MemoryContext(web_context=WebSearchContext(status="ok", results=[
            WebSearchResult(url=url, title=url, engine="google") for url in urls]))
        events = [event async for event in workflows.generate_chat_response_stream(
            "Baca sumber", context)]
        self.assertEqual(["final"], [event["delta"] for event in events if event["type"] == "delta"])
        self.assertEqual(2, workflows.web.read_url.await_count)
        request = gateway.tracked_async_completion.call_args.kwargs
        self.assertNotIn("tools", request)
        replay = next(message for message in request["messages"] if message.get("tool_calls"))
        self.assertEqual({"provider": {"opaque": "message-signature"}}, replay["extra_content"])
        self.assertEqual(["read-0", "read-1"], [call["id"] for call in replay["tool_calls"]])
        for index, call in enumerate(replay["tool_calls"]):
            self.assertNotIn("index", call)
            self.assertEqual(signature, call["extra_content"])
            self.assertEqual("read_url", call["function"]["name"])
            self.assertEqual('{"url":"' + urls[index] + '"}', call["function"]["arguments"])
        self.assertEqual(33, next(event["usage"]["total_tokens"] for event in events
                                  if event["type"] == "usage"))
        self.assertTrue(final.closed)
        client.close.assert_awaited_once()

    async def test_planner_error_before_any_text_retains_clean_fallback(self):
        planning = ControlledStream([], error=RuntimeError("planner unavailable"))
        final = ControlledStream([chunk("fallback", finish="stop")])
        workflows, gateway, _ = setup_workflow(planning, final)
        workflows.web.plan_web_search.return_value = Record(needed=False)
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan recursion", MemoryContext())]
        self.assertEqual(["fallback"], [event["delta"] for event in events if event["type"] == "delta"])
        self.assertEqual(2, gateway.tracked_async_completion.await_count)
        self.assertTrue(planning.closed)

    async def test_planner_timeout_after_text_does_not_regenerate(self):
        stream = ControlledStream([chunk("partial"), chunk("rest")])
        workflows, gateway, client = setup_workflow(stream)
        response = workflows.generate_chat_response_stream("Jelaskan recursion", MemoryContext())
        async def timeout(awaitable, *, timeout):
            awaitable.close()
            raise TimeoutError("deadline")
        try:
            await anext(response)
            with patch("app.application.chat.stream_planning_response.asyncio.wait_for",
                       side_effect=timeout):
                with self.assertRaises(TimeoutError):
                    await anext(response)
        finally:
            await response.aclose()
        self.assertTrue(stream.closed)
        self.assertEqual(1, gateway.tracked_async_completion.await_count)
        client.close.assert_awaited_once()


class PlanningStreamAssemblyTests(TestCase):
    def test_nested_metadata_is_merged_without_concatenating_opaque_values(self):
        result = PlanningStreamResult()
        for extensions in ({"google": {"thought_signature": "opaque"}},
                           {"google": {"trace": "other", "thought_signature": "opaque"}}):
            choice = chunk(tools=[{"index": 0, "id": None,
                "function": {"name": None, "arguments": ""},
                "extra_content": extensions}]).choices[0]
            result.add_choice(choice, "", "")
        payload = result.tool_calls[0].model_dump()
        self.assertEqual({"google": {"trace": "other", "thought_signature": "opaque"}},
                         payload["extra_content"])
        self.assertNotIn("index", payload)

    def test_invalid_tool_indexes_fail_closed(self):
        for index in (None, -1, True, "0"):
            with self.subTest(index=index):
                result = PlanningStreamResult()
                choice = Record(delta=Record(tool_calls=[Record(index=index,
                    function=Record(name="read_url", arguments="{}"))]))
                with self.assertRaises(ValueError):
                    result.add_choice(choice, "", "")
