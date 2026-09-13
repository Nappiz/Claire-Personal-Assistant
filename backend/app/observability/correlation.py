from contextvars import ContextVar
import logging
import re
import uuid

correlation = ContextVar("request_correlation", default={})


class CorrelationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", supplied) else str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = correlation.set({"request_id": request_id})
        try:
            await self.app(scope, receive, send)
        finally:
            correlation.reset(token)


class CorrelationFilter(logging.Filter):
    def filter(self, record):
        values = correlation.get()
        for key in ("request_id", "session_id", "turn_id"):
            setattr(record, key, values.get(key) or "-")
        return True
