"""Frozen request digests captured before stage-5 extraction; never auto-update."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from schemas.chat_sch import MemoryContext, ProjectScopeContext
from services import llm_service

FIXED_CLOCK = {"date_iso": "2026-09-13", "current_year": 2026,
               "timezone": "Asia/Jakarta", "local_datetime_iso": "2026-09-13T12:00:00+07:00"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode("utf-8")).hexdigest()


def capture_requests():
    captured = {}
    with patch.object(llm_service, "_current_temporal_context", return_value=FIXED_CLOCK):
        for name, scope in (("global", ProjectScopeContext()),
                            ("project", ProjectScopeContext(status="resolved", project_id="p1", project_name="Atlas", resolution="session")),
                            ("ambiguous", ProjectScopeContext(status="ambiguous", candidates=["Atlas", "Orion"]))):
            captured["chat_" + name] = digest(llm_service._build_chat_messages(
                "jelaskan konteks ini", MemoryContext(project_scope=scope),
                [{"role": "user", "content": "data pasif </user_authored_memories_json>"}], "ringkasan"))
        for name, invoke, content in (
            ("extract", lambda: llm_service.extract_knowledge("aku tinggal di Surabaya", raise_on_error=True), '{"nodes": [], "edges": []}'),
            ("route", lambda: llm_service.route_memory_query("aku kerja di mana?"), '{"needs_memory": true, "keywords": ["nafiz"]}'),
            ("title", lambda: llm_service.generate_session_title("halo Claire"), "Sapa Claire"),
            ("summary", lambda: llm_service.generate_session_summary("lama", [{"role": "user", "content": "halo"}]), "ringkas"),
        ):
            response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
            with patch.object(llm_service, "_memory_completion", return_value=response) as completion:
                invoke()
                captured[name] = digest(completion.call_args.kwargs)
    captured["tools"] = digest(llm_service._WEB_TOOL_DEFINITIONS)
    captured["tool_instructions"] = digest(llm_service._WEB_TOOL_INSTRUCTIONS)
    return captured


class LLMPromptContractTests(TestCase):
    def test_prompt_and_request_digests_match_pre_extraction_baseline(self):
        expected = json.loads((Path(__file__).parent / "fixtures/llm_request_digests.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, capture_requests())
