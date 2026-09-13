from types import SimpleNamespace as Record
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from app.application.llm.workflows import LLMWorkflows
from app.domain.llm.prompt_policy import ChatPromptPolicy
from app.domain.llm.memory_query_policy import MemoryQueryPolicy
from app.domain.llm.extraction_policy import ExtractionPolicy
from app.domain.llm.response_policy import ResponsePolicy
from app.domain.llm.web_tool_policy import WebToolPolicy
from app.domain.llm.location_grounding import ground_locations
from app.infrastructure.llm.openai_gateway import OpenAICompletionGateway
from app.infrastructure.llm.response_normalizer import ResponseRecord
from schemas.chat_sch import MemoryContext, QueryResolution


def fake_workflows(gateway):
    config = Record(CHAT_INPUT_TOKEN_BUDGET=12000, CHAT_OUTPUT_MAX_TOKENS=800,
                    USER_TIMEZONE="UTC", LLM_MAX_RETRIES=1, WEB_TOOL_MAX_ROUNDS=2,
                    WEB_READ_MAX_URLS=2, WEB_TOOL_PLANNING_TIMEOUT_SECONDS=5)
    prompts = ChatPromptPolicy(config)
    references = MemoryQueryPolicy(config)
    extraction = ExtractionPolicy(config, prompts=prompts)
    prompts.references, prompts.extraction = references, extraction
    web = Mock()
    async def threadpool(function, *args, **kwargs):
        return function(*args, **kwargs)
    return LLMWorkflows(gateway=gateway, config=config, web=web, prompts=prompts,
        references=references, extraction=extraction, responses=ResponsePolicy(config),
        tools=WebToolPolicy(config, web=web), ground_locations=ground_locations, threadpool=threadpool)


class LLMWorkflowBoundaryTests(TestCase):
    def test_chat_and_title_run_with_injected_fake_gateway(self):
        client = Record(close=Mock())
        gateway = Mock()
        gateway.get_llm_client.return_value = client
        gateway.tracked_sync_completion.return_value = (Record(choices=[Record(
            message=Record(content="jawaban"), finish_reason="stop")],
            usage=Record(prompt_tokens=3, completion_tokens=2, total_tokens=5)), "call1")
        gateway.memory_completion.return_value = Record(choices=[Record(message=Record(content='"Judul Singkat"'))])
        workflows = fake_workflows(gateway)
        answer, usage = workflows.generate_chat_response("halo", MemoryContext())
        self.assertEqual("jawaban", answer)
        self.assertEqual(["call1"], usage["invocation_ids"])
        self.assertEqual("Judul Singkat", workflows.generate_session_title("halo"))
        self.assertEqual("title", gateway.memory_completion.call_args.kwargs["purpose"])
        client.close.assert_called_once()

    def test_ambiguous_reference_short_circuits_provider(self):
        gateway = Mock()
        workflows = fake_workflows(gateway)
        answer, usage = workflows.generate_chat_response("dia siapa?", MemoryContext(
            query_resolution=QueryResolution(status="ambiguous", candidates=["Budi", "Adi"])))
        self.assertEqual("Yang kamu maksud Budi atau Adi?", answer)
        self.assertEqual({}, usage)
        gateway.get_llm_client.assert_not_called()

    def test_gateway_normalizes_provider_response_and_replay_metadata(self):
        signature = {"google": {"thought_signature": "opaque-signature"}}
        provider_response = Record(choices=[Record(message=Record(content=None,
            tool_calls=[Record(id="t1", function=Record(name="read_url", arguments='{"url":"https://example.test"}'), extra_content=signature)]))])
        gateway = OpenAICompletionGateway(Record())
        with patch("services.ai_usage_service.tracked_sync_completion", return_value=(provider_response, "call1")):
            response, call_id = gateway.tracked_sync_completion(object(), model="unchanged")
        self.assertIsInstance(response, ResponseRecord)
        self.assertEqual("call1", call_id)
        message = response.choices[0].message
        replay = gateway.serialized_assistant_tool_message(message, message.tool_calls)
        self.assertEqual(signature, replay["tool_calls"][0]["extra_content"])


class LLMStreamBoundaryTests(IsolatedAsyncioTestCase):
    async def test_fake_stream_retains_whitespace_and_closes_client(self):
        class Stream:
            def __init__(self):
                self.chunks = iter([Record(choices=[Record(delta=Record(content=text))], usage=None)
                                    for text in ("satu", " ", "dua")])
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            def __aiter__(self): return self
            async def __anext__(self):
                try: return next(self.chunks)
                except StopIteration: raise StopAsyncIteration
        gateway = Mock()
        client = Record(close=AsyncMock())
        gateway.get_llm_connection.return_value = ("fake", None)
        gateway.create_async_llm_client.return_value = client
        gateway.tracked_async_completion = AsyncMock(return_value=(Stream(), "call1"))
        events = [event async for event in fake_workflows(gateway).generate_chat_response_stream("halo", MemoryContext())]
        self.assertEqual("satu dua", "".join(event["delta"] for event in events if event["type"] == "delta"))
        self.assertEqual("completion", events[-1]["type"])
        client.close.assert_awaited_once()
