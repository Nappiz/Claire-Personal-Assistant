"""Published HTTP/OpenAPI and SSE contracts, independent of provider availability."""
import json
from pathlib import Path
from unittest import TestCase

from fastapi import FastAPI
from routes import chat_routes, settings_routes


def published_api():
    api = FastAPI()
    api.include_router(chat_routes.router, prefix="/api/v1")
    api.include_router(settings_routes.router, prefix="/api/v1")
    return api


class APIContractTests(TestCase):
    def test_published_openapi_matches_baseline(self):
        expected = json.loads((Path(__file__).parent / "fixtures" / "api_openapi.json").read_text(encoding="utf-8"))
        actual = published_api().openapi()
        self.assertEqual(expected["paths"], actual["paths"])
        self.assertEqual(expected["components"], actual["components"])

    def test_sse_keeps_unicode_and_exact_frame_termination(self):
        payload = {"type": "delta", "delta": "Halo\nNafiz â€” aman"}
        frame = chat_routes._sse_data(payload)
        self.assertTrue(frame.startswith("data: "))
        self.assertTrue(frame.endswith("\n\n"))
        self.assertEqual(1, frame.count("\n\n"))
        self.assertEqual(payload, json.loads(frame[6:].strip()))
