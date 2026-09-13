"""Regression coverage for web_search -> read_url -> streamed answer orchestration."""

import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from schemas.chat_sch import MemoryContext, WebPageContent, WebSearchContext, WebSearchResult
from services import llm_service, web_reader_service, web_search_service


def _tool_call(call_id: str, name: str, arguments: dict, signature: str):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        extra_content={"google": {"thought_signature": signature}},
    )


def _planning_response(*tool_calls):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=list(tool_calls)))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
    )


class _FakeStream:
    def __init__(self, chunks=None):
        self._chunks = iter(
            chunks if chunks is not None else [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Jawaban final"))],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=30, completion_tokens=4, total_tokens=34),
                ),
            ]
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _EmptyToolCallStream:
    """A 200-response stream that contains no user-visible answer text."""

    def __init__(self):
        self._chunks = iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                refusal=None,
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(name="read_url")
                                    )
                                ],
                            ),
                            finish_reason="unexpected_tool_call",
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=20,
                        completion_tokens=1,
                        total_tokens=21,
                    ),
                ),
            ]
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeLLMClient:
    def __init__(self, planning_responses, stream_responses=None):
        self.chat = self
        self.completions = self
        self.planning_responses = iter(planning_responses)
        self.stream_responses = iter(stream_responses or [])
        self.calls = []
        self.closed = False

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream") and not kwargs.get("tools"):
            return next(self.stream_responses, None) or _FakeStream()
        response = next(self.planning_responses)
        if isinstance(response, BaseException):
            raise response
        if kwargs.get("stream"):
            return _planning_stream(response)
        return response

    async def close(self):
        self.closed = True


def _planning_stream(response):
    """Return real delta-shaped fragments for the planner, not a full message."""
    chunks = []
    choices = response.choices
    if choices:
        message = choices[0].message
        content = message.content or ""
        midpoint = max(1, len(content) // 2)
        for text in (content[:midpoint], content[midpoint:]):
            if text:
                chunks.append(SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=text), finish_reason=None)], usage=None))
        calls = list(getattr(message, "tool_calls", None) or [])
        for index, call in enumerate(calls):
            arguments = call.function.arguments
            midpoint = max(1, len(arguments) // 2)
            for offset, arguments_part in enumerate((arguments[:midpoint], arguments[midpoint:])):
                fragment = SimpleNamespace(
                    index=index, id=call.id if offset == 0 else None, type="function",
                    function=SimpleNamespace(
                        name=call.function.name if offset == 0 else None,
                        arguments=arguments_part),
                    extra_content=getattr(call, "extra_content", None) if offset == 1 else None)
                chunks.append(SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                    content=None, tool_calls=[fragment]), finish_reason=None)], usage=None))
        chunks.append(SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content=None, refusal=getattr(message, "refusal", None)),
            finish_reason=getattr(choices[0], "finish_reason", None) or
                          ("tool_calls" if calls else "stop"))], usage=None))
    chunks.append(SimpleNamespace(choices=[], usage=response.usage))
    return _FakeStream(chunks)


async def _search_context(*_args, **_kwargs):
    return WebSearchContext(
        status="ok",
        query="React 19 vs React 18",
        results=[
            WebSearchResult(
                title="React 19 release notes",
                url="https://react.dev/blog/react-19",
                snippet="React 19 introduces new APIs.",
                engine="google",
            )
        ],
    )


async def _read_page(url, *, allowed_urls, title=""):
    assert url in allowed_urls
    return WebPageContent(
        title=title,
        url=url,
        content="# React 19\n\nFull release details and migration notes.",
    )


class LLMWebToolLoopTests(IsolatedAsyncioTestCase):
    async def test_real_openai_sdk_tool_call_keeps_gemini_thought_signature(self):
        tool_call = ChatCompletionMessageFunctionToolCall.model_validate(
            {
                "id": "search-1",
                "type": "function",
                "function": {"name": "web_search", "arguments": "{}"},
                "extra_content": {
                    "google": {"thought_signature": "provider-owned-signature"}
                },
            }
        )

        serialized = llm_service._serialized_tool_calls([tool_call])

        self.assertEqual(
            "provider-owned-signature",
            serialized[0]["extra_content"]["google"]["thought_signature"],
        )

    async def test_rejected_sequential_tool_history_is_not_replayed_to_final_stream(self):
        search_call = _tool_call(
            "search-1",
            "web_search",
            {"queries": ["harga rumah Pakuwon City Surabaya 2026"]},
            "signature-search",
        )
        fake_client = _FakeLLMClient(
            [_planning_response(search_call), RuntimeError("provider rejected tool history")]
        )
        context = MemoryContext()

        with (
            patch.object(llm_service, "_get_llm_connection", return_value=("key", "base")),
            patch.object(llm_service, "_create_async_llm_client", return_value=fake_client),
            patch.object(web_search_service, "retrieve_web_context", new=_search_context),
        ):
            events = [
                event
                async for event in llm_service.generate_chat_response_stream(
                    "Berapa harga rumah di Pakuwon City sekarang?",
                    context,
                    model="test-model",
                    provider="google",
                )
            ]

        self.assertEqual("Jawaban final", next(event["delta"] for event in events if event["type"] == "delta"))
        final_messages = fake_client.calls[-1]["messages"]
        self.assertTrue(fake_client.calls[-1]["stream"])
        self.assertFalse(any(message["role"] == "tool" for message in final_messages))
        self.assertFalse(any(message.get("tool_calls") for message in final_messages))
        self.assertIn("<web_tool_fallback_json>", final_messages[0]["content"])
        self.assertIn("https://react.dev/blog/react-19", final_messages[0]["content"])

    async def test_searches_reads_allowlisted_page_then_streams_same_thread(self):
        search_call = _tool_call(
            "search-1",
            "web_search",
            {"queries": ["React 19 vs React 18 fundamental differences"]},
            "signature-search",
        )
        read_call = _tool_call(
            "read-1",
            "read_url",
            {"url": "https://react.dev/blog/react-19"},
            "signature-read",
        )
        fake_client = _FakeLLMClient(
            [_planning_response(search_call), _planning_response(read_call)]
        )
        context = MemoryContext()

        with (
            patch.object(llm_service, "_get_llm_connection", return_value=("key", "base")),
            patch.object(llm_service, "_create_async_llm_client", return_value=fake_client),
            patch.object(web_search_service, "retrieve_web_context", new=_search_context),
            patch.object(web_reader_service, "read_url", new=_read_page),
        ):
            events = [
                event
                async for event in llm_service.generate_chat_response_stream(
                    "Apa perbedaan fundamental React 19 dan React 18?",
                    context,
                    model="test-model",
                    provider="google",
                )
            ]

        self.assertEqual(
            ["searching", "reading", "complete"],
            [event["phase"] for event in events if event["type"] == "web_search"],
        )
        self.assertEqual("Jawaban final", next(event["delta"] for event in events if event["type"] == "delta"))
        usage = next(event["usage"] for event in events if event["type"] == "usage")
        self.assertEqual(58, usage["total_tokens"])
        self.assertEqual(1, len(context.web_context.pages))
        self.assertTrue(fake_client.closed)
        self.assertEqual(3, len(fake_client.calls))
        self.assertTrue(fake_client.calls[0]["stream"])
        self.assertTrue(fake_client.calls[1]["stream"])
        self.assertTrue(fake_client.calls[2]["stream"])
        self.assertNotIn("tools", fake_client.calls[2])
        self.assertNotIn("tool_choice", fake_client.calls[2])
        final_messages = fake_client.calls[2]["messages"]
        self.assertEqual(2, sum(message["role"] == "tool" for message in final_messages))
        assistant_tool_messages = [
            message for message in final_messages if message["role"] == "assistant"
        ]
        self.assertEqual(
            "signature-search",
            assistant_tool_messages[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"],
        )
        self.assertEqual(
            "signature-read",
            assistant_tool_messages[1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"],
        )
        self.assertIn("Full release details", final_messages[-1]["content"])

    async def test_empty_final_stream_recovers_without_repeating_web_tools(self):
        search_call = _tool_call(
            "search-1",
            "web_search",
            {"queries": ["React 19 vs React 18 fundamental differences"]},
            "signature-search",
        )
        read_call = _tool_call(
            "read-1",
            "read_url",
            {"url": "https://react.dev/blog/react-19"},
            "signature-read",
        )
        fake_client = _FakeLLMClient(
            [_planning_response(search_call), _planning_response(read_call)],
            stream_responses=[_EmptyToolCallStream(), _FakeStream()],
        )
        context = MemoryContext()

        with (
            patch.object(llm_service, "_get_llm_connection", return_value=("key", "base")),
            patch.object(llm_service, "_create_async_llm_client", return_value=fake_client),
            patch.object(web_search_service, "retrieve_web_context", new=_search_context),
            patch.object(web_reader_service, "read_url", new=_read_page),
        ):
            events = [
                event
                async for event in llm_service.generate_chat_response_stream(
                    "Apa perbedaan fundamental React 19 dan React 18?",
                    context,
                    model="test-model",
                    provider="google",
                )
            ]

        self.assertEqual(
            ["searching", "reading", "complete"],
            [event["phase"] for event in events if event["type"] == "web_search"],
        )
        self.assertEqual(
            ["Jawaban final"],
            [event["delta"] for event in events if event["type"] == "delta"],
        )
        self.assertEqual(4, len(fake_client.calls))
        self.assertTrue(fake_client.calls[2]["stream"])
        self.assertTrue(fake_client.calls[3]["stream"])

        recovery_messages = fake_client.calls[3]["messages"]
        self.assertFalse(any(message["role"] == "tool" for message in recovery_messages))
        self.assertFalse(any(message.get("tool_calls") for message in recovery_messages))
        self.assertIn("FINAL RESPONSE RECOVERY", recovery_messages[0]["content"])
        self.assertIn("<web_recovery_context_json>", recovery_messages[0]["content"])
        self.assertIn("Full release details", recovery_messages[0]["content"])
        self.assertIn("https://react.dev/blog/react-19", recovery_messages[0]["content"])
        self.assertTrue(fake_client.closed)
