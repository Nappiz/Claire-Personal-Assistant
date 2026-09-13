"""Executable architecture and privacy gates."""
import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from app.observability.operational_events import emit_event
from app.observability.correlation import correlation
from app.infrastructure.memory.api_workflows import BoundMemoryWorkflows
from schemas.chat_sch import MemoryContext

path = Path(__file__).resolve().parents[1] / "scripts/check_architecture.py"
spec = importlib.util.spec_from_file_location("architecture_check", path)
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


class ArchitectureGateTests(TestCase):
    def violations(self, path, source):
        return architecture.dependency_graph({path:source})[1]

    def test_production_cannot_import_legacy_services(self):
        self.assertTrue(self.violations("app/infrastructure/test.py","from services import memory_service"))

    def test_worker_cannot_import_provider_or_persistence(self):
        self.assertTrue(self.violations("app/workers/test.py","import sqlalchemy"))
        self.assertTrue(self.violations("app/workers/test.py","from configs.database import SessionLocal"))

    def test_private_import_across_package_is_rejected(self):
        self.assertTrue(self.violations("app/application/memory/test.py","from app.domain.llm.policy import _helper"))

    def test_domain_cannot_import_infrastructure(self):
        self.assertTrue(self.violations("app/domain/test.py","import app.infrastructure.llm"))

    def test_cycle_detection(self):
        self.assertEqual([["a","b"]], architecture.cycles({"a":{"b"},"b":{"a"}}))

    def test_stale_module_import_is_rejected(self):
        self.assertTrue(self.violations("app/api/test.py", "from app.infrastructure.removed_bridge import gateway"))


class OperationalPrivacyTests(TestCase):
    def test_allowlist_excludes_private_content(self):
        token = correlation.set({"request_id":"request-1","session_id":"session-1","turn_id":"turn-1"})
        try:
            with patch("app.observability.operational_events.logger") as logger:
                emit_event("ai.started", provider="google", model="same", prompt="PRIVATE", api_key="SECRET", memory_text="PRIVATE")
            payload = logger.info.call_args.args[2]
            self.assertNotIn("PRIVATE",payload)
            self.assertNotIn("SECRET",payload)
            self.assertIn("request-1",payload)
        finally:
            correlation.reset(token)

    def test_log_outage_cannot_fail_operation(self):
        with patch("app.observability.operational_events.logger.info",side_effect=RuntimeError("logging offline")):
            emit_event("ai.started", provider="google")

    def test_retrieval_logs_ids_not_content(self):
        workflows = Mock()
        context = MemoryContext(qdrant_context=[{"content":"private assertion","score":0.8,"message_id":"source-1"}])
        workflows.retrieve_context.return_value = context
        with patch("app.infrastructure.memory.api_workflows.emit_event") as event:
            self.assertIs(context,BoundMemoryWorkflows(workflows).retrieve_context("private question"))
        event.assert_called_once_with("memory.retrieved",candidate_ids=["source-1"])
