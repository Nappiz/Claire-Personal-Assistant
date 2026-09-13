"""Run the offline backend suite with isolated runtime storage.

Usage from the repository root: backend/venv/Scripts/python.exe backend/scripts/run_tests.py
Pass optional unittest patterns as positional arguments (default: test_*.py).
"""
from __future__ import annotations

import os
import json
import logging
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend / "tests"))
    with tempfile.TemporaryDirectory(prefix="claire-tests-") as directory:
        os.environ.update({
            "DATABASE_URL": "sqlite:///" + str(Path(directory) / "test.db").replace("\\", "/"),
            "QDRANT_PATH": str(Path(directory) / "qdrant"),
            "NEO4J_URI": "bolt://127.0.0.1:1",
            "NEO4J_USER": "test",
            "NEO4J_PASSWORD": "test",
            "GROQ_API_KEY": "offline-test-key",
            "GEMINI_API_KEY": "offline-test-key",
            "HF_HUB_OFFLINE": "1",
        })
        suite = unittest.TestSuite()
        original_connect = socket.socket.connect
        original_pair = socket.socketpair
        pair_state = threading.local()

        def offline_connect(sock, address):
            if getattr(pair_state, "creating", False):
                return original_connect(sock, address)
            raise OSError("Offline test: network disabled")

        def local_socketpair(*args, **kwargs):
            pair_state.creating = True
            try:
                return original_pair(*args, **kwargs)
            finally:
                pair_state.creating = False

        logging.getLogger().handlers = [logging.NullHandler()]
        # A real provider call in an offline test must fail rather than touching
        # local user stores or sending credentials/content over the network.
        with patch.object(socket.socket, "connect", offline_connect), patch.object(socket, "socketpair", local_socketpair):
            for pattern in sys.argv[1:] or ["test_*.py"]:
                suite.addTests(unittest.defaultTestLoader.discover(str(backend / "tests"), pattern=pattern))
            def test_ids(tests):
                return [identifier for test in tests for identifier in
                        (test_ids(test) if isinstance(test, unittest.TestSuite) else [test.id()])]
            planned = test_ids(suite)
            result = unittest.TextTestRunner(verbosity=1).run(suite)
        report = backend / ".refactor" / "test-results.json"
        report.parent.mkdir(exist_ok=True)
        report.write_text(json.dumps({
            "tests": result.testsRun,
            "test_ids": planned,
            "failures": [test.id() for test, _ in result.failures],
            "errors": [test.id() for test, _ in result.errors],
            "skipped": [(test.id(), reason) for test, reason in result.skipped],
        }, indent=2), encoding="utf-8")
        if "configs.database" in sys.modules:
            sys.modules["configs.database"].engine.dispose()
        if "app.infrastructure.vector.state" in sys.modules:
            client = sys.modules["app.infrastructure.vector.state"].client
            if client is not None:
                client.close()
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
