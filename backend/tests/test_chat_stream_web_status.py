"""SSE regression coverage for live web-search status events."""

import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from fastapi import BackgroundTasks

from routes import chat_routes
from schemas.chat_sch import ChatRequest, MemoryContext, WebPageContent, WebSearchContext, WebSearchResult


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def _llm_stream(_message, context: MemoryContext, *_args, **_kwargs):
    result = WebSearchResult(
        title="Harga BBM terbaru",
        url="https://example.com/bbm",
        engine="google",
    )
    page = WebPageContent(
        title=result.title,
        url=result.url,
        content="Isi lengkap halaman",
    )
    context.web_context = WebSearchContext(
        status="ok",
        query="harga pertamax hari ini Indonesia",
        results=[result],
        pages=[page],
    )
    yield {
        "type": "web_search",
        "phase": "searching",
        "query": context.web_context.query,
        "queries": [context.web_context.query],
        "engines": ["google"],
    }
    yield {
        "type": "web_search",
        "phase": "reading",
        "pages": [{"title": page.title, "url": page.url}],
    }
    yield {
        "type": "web_search",
        "phase": "complete",
        "status": "ok",
        "query": context.web_context.query,
        "results": [{"title": result.title, "url": result.url, "engine": result.engine}],
        "pages": [{"title": page.title, "url": page.url}],
    }
    yield {"type": "delta", "delta": "Jawaban"}


class ChatStreamWebStatusTests(IsolatedAsyncioTestCase):
    async def test_search_status_precedes_llm_delta_and_includes_sources(self):
        with (
            patch.object(
                chat_routes,
                "_prepare_stream_session",
                return_value=("session-1", False, [], None),
            ),
            patch.object(
                chat_routes.memory_service,
                "retrieve_context",
                return_value=MemoryContext(),
            ),
            patch.object(
                chat_routes.llm_service,
                "generate_chat_response_stream",
                new=_llm_stream,
            ),
            patch.object(
                chat_routes.memory_service,
                "save_interaction",
                return_value={
                    "user_message_id": "user-1",
                    "assistant_message_id": "assistant-1",
                    "memory_job_id": "job-1",
                    "memory_job": {"status": "completed"},
                },
            ),
        ):
            response = await chat_routes.stream_chat_endpoint(
                ChatRequest(message="berapa harga pertamax hari ini?"),
                _ConnectedRequest(),
                BackgroundTasks(),
            )
            events = []
            async for frame in response.body_iterator:
                data = frame.removeprefix("data: ").strip()
                events.append(json.loads(data))

        self.assertEqual(
            ["session", "web_search", "web_search", "web_search", "delta", "done"],
            [event["type"] for event in events],
        )
        self.assertEqual("searching", events[1]["phase"])
        self.assertEqual("reading", events[2]["phase"])
        self.assertEqual("complete", events[3]["phase"])
        self.assertEqual("ok", events[3]["status"])
        self.assertEqual("Harga BBM terbaru", events[3]["results"][0]["title"])
        self.assertEqual("Harga BBM terbaru", events[3]["pages"][0]["title"])

    async def test_memory_failure_does_not_replace_a_successful_answer(self):
        with (
            patch.object(
                chat_routes,
                "_prepare_stream_session",
                return_value=("session-1", False, [], None),
            ),
            patch.object(
                chat_routes.memory_service,
                "retrieve_context",
                return_value=MemoryContext(),
            ),
            patch.object(
                chat_routes.llm_service,
                "generate_chat_response_stream",
                new=_llm_stream,
            ),
            patch.object(
                chat_routes.memory_service,
                "save_interaction",
                return_value={
                    "user_message_id": "user-1",
                    "assistant_message_id": "assistant-1",
                    "memory_job_id": "job-1",
                    "memory_job": {
                        "status": "failed",
                        "reportable_operation": "knowledge_extraction",
                        "reportable_error_log": "Traceback: schema validation failed",
                    },
                },
            ),
            patch.object(
                chat_routes.llm_service,
                "analyze_internal_error",
                return_value="Extractor menghasilkan data yang tidak lolos validasi schema.",
            ),
            patch.object(chat_routes.memory_service, "record_internal_error") as record_error,
        ):
            response = await chat_routes.stream_chat_endpoint(
                ChatRequest(message="simpan fakta ini"),
                _ConnectedRequest(),
                BackgroundTasks(),
            )
            events = []
            async for frame in response.body_iterator:
                data = frame.removeprefix("data: ").strip()
                events.append(json.loads(data))

        self.assertEqual("done", events[-1]["type"])
        self.assertNotIn("internal_error", [event["type"] for event in events])
        record_error.assert_not_called()
