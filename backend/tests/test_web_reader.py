"""Regression coverage for the bounded, allowlisted Jina Reader integration."""

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from services import web_reader_service


class _FakeReaderResponse:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    async def aiter_text(self):
        yield "# Article\n\n"
        yield "Useful content " * 1000


class _FakeReaderClient:
    def __init__(self, **_kwargs):
        self.request_url = ""
        self.request_headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, _method, url, *, headers):
        self.request_url = url
        self.request_headers = headers
        return _FakeReaderResponse()


class WebReaderTests(IsolatedAsyncioTestCase):
    async def test_rejects_url_not_returned_by_search(self):
        with self.assertRaises(web_reader_service.WebReadRejectedError):
            await web_reader_service.read_url(
                "https://attacker.example/private",
                allowed_urls={"https://safe.example/article"},
            )

    async def test_reads_through_jina_and_bounds_markdown(self):
        fake_client = _FakeReaderClient()
        with (
            patch.object(web_reader_service.httpx, "AsyncClient", return_value=fake_client),
            patch.object(web_reader_service.settings, "WEB_READ_MAX_CHARS", 4000),
            patch.object(web_reader_service.settings, "JINA_READER_URL", "https://r.jina.ai"),
            patch.object(web_reader_service.settings, "JINA_API_KEY", None),
        ):
            page = await web_reader_service.read_url(
                "https://safe.example/article#section",
                allowed_urls={"https://safe.example/article"},
                title="Safe article",
            )

        self.assertEqual("https://safe.example/article", page.url)
        self.assertEqual("Safe article", page.title)
        self.assertLessEqual(len(page.content), 4000)
        self.assertIn("Content truncated", page.content)
        self.assertEqual(
            "https://r.jina.ai/https://safe.example/article",
            fake_client.request_url,
        )
        self.assertEqual("text/markdown", fake_client.request_headers["Accept"])
