"""Regressions from fresh-fact requests, irrelevant search and leaked tool JSON."""
import asyncio
import json
from types import SimpleNamespace as Record
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app.domain.web.intent_policy import plan_web_search
from app.domain.web.evidence_policy import filter_search_evidence, query_matches_topic
from app.domain.llm.tool_text_policy import VisibleTextGate, tool_envelope
from app.domain.llm.web_tool_policy import WebToolPolicy
from schemas.chat_sch import MemoryContext, ProjectScopeContext, WebSearchContext, WebSearchResult
from services import web_search_service
from test_chat_planning_stream import ControlledStream, chunk, setup_workflow
from test_web_search import _FakeAsyncClient, _FakeResponse


class SearchRequirementTests(TestCase):
    def test_fresh_public_facts_require_search_without_magic_search_word(self):
        for message in ("harga pertamina", "daftar hero ML terbaru season skrg",
                        "tarif listrik", "kurs yen", "apakah Shell masih beroperasi sekarang"):
            with self.subTest(message=message):
                self.assertTrue(plan_web_search(message).needed)

    def test_fallback_removes_conversational_search_boilerplate(self):
        plan = plan_web_search("tolong cari harga pertamina di internet")
        self.assertEqual("harga pertamina", plan.query)
        self.assertEqual(plan.query, plan.research_goal)

    def test_prose_and_normal_json_are_preserved_but_tool_json_is_not(self):
        for text in ('{"answer":"safe"}', " biasa\n", "satu dua"):
            gate = VisibleTextGate()
            output = "".join(gate.feed(character) for character in text) + gate.finish()
            self.assertEqual(text, output)
        for text in ('{"action":"web_search","action_input":"harga"}',
                     '```json\n{"action":"web_search","action_input":"harga"}\n```',
                     '{"action":"web_search","action_input":'):
            gate = VisibleTextGate()
            output = "".join(gate.feed(character) for character in text) + gate.finish()
            self.assertEqual("", output)

    def test_query_rewrites_allow_acronyms_but_not_unrelated_topic(self):
        self.assertTrue(query_matches_topic("Mobile Legends heroes latest season", "daftar hero ML terbaru"))
        self.assertFalse(query_matches_topic("sambutan presiden rapat nasional", "harga pertamina"))

    def test_dated_old_results_cannot_satisfy_requested_period(self):
        results = [
            WebSearchResult(title="Harga Pertamina 2017", url="https://example.com/2017",
                            published_at="2017-07-20"),
            WebSearchResult(title="Harga Pertamina 2026", url="https://example.com/2026"),
        ]
        self.assertEqual([results[1]], filter_search_evidence(results, "harga pertamina September 2026"))

    def test_shared_location_alone_is_not_evidence_for_a_product_price(self):
        results = [WebSearchResult(title="Sambutan Presiden Indonesia 2026",
                                  url="https://example.com/presiden")]
        self.assertEqual([], filter_search_evidence(results, "harga BBM Pertamina Indonesia 2026"))

    def test_fresh_public_question_does_not_override_owned_project_privacy(self):
        policy = WebToolPolicy(Record())
        context = MemoryContext(project_scope=ProjectScopeContext(
            status="resolved", project_id="p1", project_name="Atlas", resolution="semantic"))
        self.assertFalse(policy.web_tools_allowed_for_turn("schema terbaru project-ku", context))
        self.assertFalse(policy.web_tools_allowed_for_turn("versi terbaru Atlas", context))
        self.assertTrue(policy.web_tools_allowed_for_turn("harga pertamina", context))
        self.assertTrue(policy.web_tools_allowed_for_turn("cari dokumentasi web untuk Atlas", context))
        self.assertTrue(policy.web_tools_allowed_for_turn("harga CloudBox terbaru untuk project Atlas", context))
        self.assertFalse(policy.web_tools_allowed_for_turn("schema terbaru untuk project-ku", context))

    def test_stale_model_query_is_replaced_with_latest_user_target(self):
        policy = WebToolPolicy(Record(), web=Record(WebSearchPlan=web_search_service.WebSearchPlan))
        call = Record(function=Record(arguments=json.dumps({
            "queries": ["kuliah TI AI"], "research_goal": "belajar kuliah TI"})))
        plan = policy.web_search_plan_from_call(call, "cari harga pertamina di internet")
        self.assertEqual(("harga pertamina",), plan.queries)
        self.assertEqual("harga pertamina", plan.research_goal)


class FunctionToolTextTests(TestCase):
    def test_literal_function_call_is_normalized_without_execution(self):
        for text in ('web_search(query="harga pertamina")',
                     "web_search(query='harga pertamina')",
                     '`web_search(query="harga pertamina")`',
                     '```python\nweb_search(query="harga pertamina")\n```'):
            with self.subTest(text=text):
                self.assertEqual({"action": "web_search",
                                  "action_input": {"queries": ["harga pertamina"]}},
                                 tool_envelope(text))
        self.assertEqual({"action": "web_search", "action_input": {
            "queries": ["harga pertamina", "harga bbm"], "research_goal": "harga"}},
            tool_envelope('web_search(queries=["harga pertamina", "harga bbm"], research_goal="harga")'))

    def test_tool_notation_never_leaks_at_any_chunk_boundary(self):
        for text in ('web_search(query="harga pertamina")',
                     '  web_search \n(query="harga pertamina")',
                     '`web_search(query="harga pertamina")`',
                     '```python\nweb_search(query="harga pertamina")\n```',
                     'read_url(url="https://example.com")',
                     'web_search(query="unfinished',
                     'web_search(query=__import__("os").getcwd())'):
            for split in range(len(text) + 1):
                with self.subTest(text=text, split=split):
                    gate = VisibleTextGate()
                    self.assertEqual("", gate.feed(text[:split]) +
                                     gate.feed(text[split:]) + gate.finish())
            gate = VisibleTextGate()
            self.assertEqual("", "".join(gate.feed(char) for char in text) + gate.finish())

    def test_prose_with_shared_prefix_is_preserved_and_streams(self):
        for text in ("website ini bagus", "web_search adalah nama fungsi.",
                     "read_url tidak dipanggil.", "web", "w", "read", "web_search",
                     "Contoh: web_search(query='x')", '`web_search`'):
            with self.subTest(text=text):
                gate = VisibleTextGate()
                self.assertEqual(text, "".join(gate.feed(char) for char in text) + gate.finish())
        gate = VisibleTextGate()
        self.assertEqual("", gate.feed("web"))
        self.assertEqual("website", gate.feed("site"))
        self.assertEqual(" bagus", gate.feed(" bagus"))

    def test_nonliteral_or_unsupported_calls_cannot_become_search_plans(self):
        for text in ('web_search(query=__import__("os").getcwd())',
                     'web_search(query="x" + "y")', 'web_search("x")',
                     'web_search(**{"query": "x"})', 'web_search(query=42)',
                     'web_search(queries=["x", 42])', 'web_search(query="x", query="y")',
                     'web_search(query="x", unexpected=True)',
                     'web_search(query="x"); read_url(url="https://example.com")',
                     'other.web_search(query="x")', 'delete_database(query="x")'):
            with self.subTest(text=text):
                self.assertIsNone(tool_envelope(text))


class SearchEvidenceTests(IsolatedAsyncioTestCase):
    async def test_captcha_engine_failure_is_unavailable_not_no_results(self):
        client = _FakeAsyncClient(response=_FakeResponse({
            "results": [], "unresponsive_engines": [["google", "Suspended: CAPTCHA"]]}))
        with patch.object(web_search_service.httpx, "AsyncClient", return_value=client), patch.object(
            web_search_service.settings, "WEB_SEARCH_ENABLED", True):
            result = await web_search_service.retrieve_web_context("harga pertamina")
        self.assertEqual("unavailable", result.status)
        self.assertEqual([], result.results)

    async def test_unrelated_engine_results_are_not_accepted_as_evidence(self):
        client = _FakeAsyncClient(response=_FakeResponse({"results": [
            {"title": "Sambutan Presiden pada Rapat Kerja",
             "url": "https://setkab.go.id/rapat-2017", "content": "cari informasi di internet",
             "engine": "google"},
            {"title": "Yakin Mau Kuliah TI?", "url": "https://example.com/kuliah",
             "content": "Baca sebelum mendaftar", "engine": "google"},
        ]}))
        with patch.object(web_search_service.httpx, "AsyncClient", return_value=client), patch.object(
            web_search_service.settings, "WEB_SEARCH_ENABLED", True):
            result = await web_search_service.retrieve_web_context("harga pertamina",
                plan=web_search_service.WebSearchPlan(True, query="harga pertamina",
                    queries=("harga pertamina",), research_goal="harga pertamina"))
        self.assertEqual("no_results", result.status)
        self.assertEqual([], result.results)


class WebToolReliabilityTests(IsolatedAsyncioTestCase):
    def evidence(self):
        return WebSearchContext(status="ok", query="harga pertamina", results=[
            WebSearchResult(title="Harga Pertamina", url="https://example.com/pertamina",
                            snippet="Harga perlu dicocokkan dengan wilayah dan tanggal.", engine="google")])

    async def test_ignored_forced_tool_cannot_stream_unverified_price(self):
        planner = ControlledStream([chunk("Harga fiktif Rp 99999.", finish="stop")])
        answer = ControlledStream([chunk("Bukti tersedia di sumber.", finish="stop")])
        workflows, gateway, _ = setup_workflow(planner, answer)
        workflows.web.plan_web_search.side_effect = plan_web_search
        workflows.web.retrieve_web_context = AsyncMock(return_value=self.evidence())
        events = [event async for event in workflows.generate_chat_response_stream(
            "harga pertamina", MemoryContext())]
        request = gateway.tracked_async_completion.await_args_list[0].kwargs
        self.assertEqual({"type": "function", "function": {"name": "web_search"}},
                         request["tool_choice"])
        workflows.web.retrieve_web_context.assert_awaited_once()
        self.assertNotIn("99999", "".join(event["delta"] for event in events if event["type"] == "delta"))
        self.assertTrue(any(event.get("phase") == "searching" for event in events))

    async def test_textual_tool_directive_is_executed_without_leaking_json(self):
        text = json.dumps({"action": "web_search", "action_input": "harga pertamina",
                           "research_goal": "harga pertamina"})
        planner = ControlledStream([chunk(text[:1]), chunk(text[1:10]), chunk(text[10:], finish="stop")])
        answer = ControlledStream([chunk("Jawaban berdasarkan sumber.", finish="stop")])
        workflows, _, _ = setup_workflow(planner, answer)
        workflows.web.WebSearchPlan = web_search_service.WebSearchPlan
        workflows.web.plan_web_search.side_effect = plan_web_search
        workflows.web.retrieve_web_context = AsyncMock(return_value=self.evidence())
        events = [event async for event in workflows.generate_chat_response_stream(
            "cari harga pertamina di internet", MemoryContext())]
        workflows.web.retrieve_web_context.assert_awaited_once()
        self.assertEqual("harga pertamina",
            workflows.web.retrieve_web_context.call_args.kwargs["plan"].query)
        visible = "".join(event["delta"] for event in events if event["type"] == "delta")
        self.assertNotIn("action_input", visible)

    async def test_no_results_returns_honest_limit_without_model_hallucination(self):
        planner = ControlledStream([chunk("Harga fiktif.", finish="stop")])
        workflows, gateway, _ = setup_workflow(planner)
        workflows.web.plan_web_search.side_effect = plan_web_search
        workflows.web.retrieve_web_context = AsyncMock(
            return_value=WebSearchContext(status="no_results", query="harga pertamina"))
        events = [event async for event in workflows.generate_chat_response_stream(
            "harga pertamina", MemoryContext())]
        visible = "".join(event["delta"] for event in events if event["type"] == "delta")
        self.assertNotIn("Harga fiktif", visible)
        self.assertTrue(visible.strip())
        self.assertEqual(1, gateway.tracked_async_completion.await_count)
        self.assertEqual("completion", events[-1]["type"])

    async def test_function_notation_planner_uses_existing_search_fallback_once(self):
        query = "penyebab kelangkaan bbm shell indonesia september 2026"
        text = f'web_search(query="{query}")'
        workflows, gateway, _ = setup_workflow(
            ControlledStream([chunk(char) for char in text] + [chunk("", finish="stop")]),
            ControlledStream([chunk("Jawaban berdasarkan sumber.", finish="stop")]))
        workflows.web.WebSearchPlan = web_search_service.WebSearchPlan
        workflows.web.plan_web_search.side_effect = plan_web_search
        workflows.web.retrieve_web_context = AsyncMock(return_value=self.evidence())
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan kelangkaan BBM Shell", MemoryContext())]
        workflows.web.retrieve_web_context.assert_awaited_once()
        self.assertEqual(query, workflows.web.retrieve_web_context.call_args.kwargs["plan"].query)
        self.assertEqual(2, gateway.tracked_async_completion.await_count)
        self.assertEqual("Jawaban berdasarkan sumber.", "".join(
            event["delta"] for event in events if event["type"] == "delta"))

    async def test_final_function_notation_recovers_without_executing_search(self):
        text = 'web_search(query="penyebab kelangkaan bbm shell indonesia september 2026")'
        workflows, gateway, _ = setup_workflow(
            ControlledStream([chunk("", finish="stop")]),
            ControlledStream([chunk(char) for char in text] + [chunk("", finish="stop")]),
            ControlledStream([chunk("Jawaban pemulihan.", finish="stop")]))
        workflows.web.plan_web_search.side_effect = plan_web_search
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan recursion", MemoryContext())]
        self.assertEqual("Jawaban pemulihan.", "".join(
            event["delta"] for event in events if event["type"] == "delta"))
        self.assertEqual(3, gateway.tracked_async_completion.await_count)
        workflows.web.retrieve_web_context.assert_not_called()

    async def test_cancellation_while_tool_prefix_is_held_closes_without_fallback(self):
        gate = asyncio.Event()
        stream = ControlledStream([chunk("web_"), chunk('search(query="x")')], gate=gate)
        workflows, gateway, client = setup_workflow(stream)
        response = workflows.generate_chat_response_stream("Jelaskan recursion", MemoryContext())
        pending = asyncio.create_task(anext(response))
        try:
            await asyncio.wait_for(stream.waiting.wait(), timeout=1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        finally:
            gate.set()
            if not pending.done():
                pending.cancel()
            await response.aclose()
        self.assertTrue(stream.closed)
        client.close.assert_awaited_once()
        self.assertEqual(1, gateway.tracked_async_completion.await_count)
        workflows.web.retrieve_web_context.assert_not_called()

    async def test_final_text_tool_json_is_not_displayed_or_executed(self):
        text = '{"action":"web_search","action_input":"another search","research_goal":"another"}'
        workflows, gateway, _ = setup_workflow(
            ControlledStream([chunk(""), chunk("", finish="stop")]),
            ControlledStream([chunk(text, finish="stop")]),
            ControlledStream([chunk("Jawaban pemulihan.", finish="stop")]))
        workflows.web.plan_web_search.side_effect = plan_web_search
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan recursion", MemoryContext())]
        visible = "".join(event["delta"] for event in events if event["type"] == "delta")
        self.assertNotIn("action_input", visible)
        self.assertIn("Jawaban pemulihan", visible)
        workflows.web.retrieve_web_context.assert_not_called()

    async def test_repeated_invalid_final_tool_json_has_bounded_honest_recovery(self):
        text = '{"action":"web_search","action_input":"another search"}'
        workflows, gateway, _ = setup_workflow(
            ControlledStream([chunk("", finish="stop")]),
            ControlledStream([chunk(text, finish="stop")]),
            ControlledStream([chunk(text, finish="stop")]))
        workflows.web.plan_web_search.side_effect = plan_web_search
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan recursion", MemoryContext())]
        visible = "".join(event["delta"] for event in events if event["type"] == "delta")
        self.assertNotIn("action_input", visible)
        self.assertTrue(visible.strip())
        self.assertEqual(3, gateway.tracked_async_completion.await_count)
        workflows.web.retrieve_web_context.assert_not_called()

    async def test_unknown_text_tool_cannot_execute_arbitrary_action(self):
        text = '{"action":"delete_database","action_input":"everything"}'
        workflows, _, _ = setup_workflow(
            ControlledStream([chunk(text, finish="stop")]),
            ControlledStream([chunk("Jawaban pemulihan.", finish="stop")]))
        workflows.web.plan_web_search.side_effect = plan_web_search
        events = [event async for event in workflows.generate_chat_response_stream(
            "Jelaskan recursion", MemoryContext())]
        self.assertNotIn("delete_database", "".join(
            event["delta"] for event in events if event["type"] == "delta"))
        workflows.web.retrieve_web_context.assert_not_called()
