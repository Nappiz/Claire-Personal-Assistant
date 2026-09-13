"""Provider-call telemetry; missing usage/cost stays unknown, never a fake zero."""
import asyncio
import logging
import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool
from openai import APIConnectionError, APIStatusError
from models.ai_invocation import AIInvocation
from configs.settings import settings
from app.domain.llm.prompt_versions import PROMPT_VERSIONS
from app.observability.operational_events import emit_event

logger = logging.getLogger("services.ai_usage_service")
_context = ContextVar("ai_usage_context", default={})


def set_usage_context(**values):
    return _context.set({**_context.get(), **values})


def reset_usage_context(token):
    _context.reset(token)


@contextmanager
def usage_context(**values):
    token = set_usage_context(**values)
    try:
        yield
    finally:
        reset_usage_context(token)


def _persist(call_id, values):
    from configs.database import SessionLocal
    db = None
    try:
        db = SessionLocal()
        row = db.get(AIInvocation, call_id)
        if row is None:
            row = AIInvocation(id=call_id)
            db.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        db.commit()
    except Exception:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                logger.warning("AI invocation telemetry rollback failed: %s", call_id)
        # A telemetry outage must not discard a successful answer. Keep the
        # exact same call ID in fallback logs for later reconciliation.
        logger.warning("AI invocation telemetry fallback: %s",
                       json.dumps({"id": call_id, **values}, default=str, ensure_ascii=False))
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.warning("AI invocation telemetry cleanup failed: %s", call_id)


def begin_call(purpose, provider, model, attempt=1):
    call_id = str(uuid.uuid4())
    context = _context.get()
    values = {"purpose": purpose, "provider": provider or "google", "model": model,
              "attempt": attempt, "status": "started", "started_at": datetime.now(timezone.utc),
              "usage_available": False, "total_cost": None}
    for key in ("conversation_id", "turn_id", "job_id", "job_attempt"):
        if context.get(key) is not None:
            values[key] = context[key]
    _persist(call_id, values)
    version_purpose = {"chat_planning": "chat", "memory_router": "router"}.get(purpose, purpose)
    emit_event("ai.started", invocation_id=call_id, provider=values["provider"],
               model=model, purpose=purpose, prompt_version=PROMPT_VERSIONS.get(version_purpose, "pre-stage5-v1"))
    return {"id": call_id, "started": time.monotonic(), "values": values}


def finish_call(call, *, response=None, usage=None, finish_reason=None, error=None, cancelled=False, response_id=None):
    usage = usage if usage is not None else getattr(response, "usage", None)
    try:
        details = (usage.model_dump(exclude_none=True) if hasattr(usage, "model_dump") else
                   dict(usage) if isinstance(usage, dict) else vars(usage) if hasattr(usage, "__dict__") else None)
        if not isinstance(details, dict):
            details = None
    except Exception:
        # Usage metadata is ancillary; an incompatible provider extension
        # must not turn a usable answer into a failed chat request.
        logger.warning("AI invocation usage metadata unavailable: %s", call["id"])
        details = None
    choices = getattr(response, "choices", None) or []
    if finish_reason is None and choices:
        finish_reason = getattr(choices[0], "finish_reason", None)
    finish_reason = str(getattr(finish_reason, "value", finish_reason)) if finish_reason else None
    status = "cancelled" if cancelled else "failed" if error else (
        "incomplete" if str(finish_reason or "").lower() in {"length", "max_tokens", "max_output_tokens", "content_filter"}
        else "success"
    )
    values = {**call["values"], "status": status, "finished_at": datetime.now(timezone.utc),
              "latency_ms": max((time.monotonic() - call["started"]) * 1000, 0),
              "finish_reason": finish_reason, "error_type": type(error).__name__ if error else None,
              "provider_request_id": getattr(response, "_request_id", None)
              or (getattr(response, "headers", {}) or {}).get("x-request-id"),
              "response_id": response_id or getattr(response, "id", None),
              "usage_available": details is not None, "usage_details": details}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = details.get(key) if details else None
        values[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    if values["total_tokens"] is None and all(values[key] is not None for key in ("prompt_tokens", "completion_tokens")):
        values["total_tokens"] = values["prompt_tokens"] + values["completion_tokens"]
    _persist(call["id"], values)
    emit_event("ai.finished", invocation_id=call["id"], **{key: values.get(key) for key in
        ("provider", "model", "purpose", "status", "latency_ms", "prompt_tokens",
         "completion_tokens", "total_tokens", "total_cost")})


def _retryable(error):
    return isinstance(error, APIConnectionError) or (
        isinstance(error, APIStatusError) and (error.status_code in {408, 409, 429} or error.status_code >= 500)
    )


def _without_sdk_retry(client):
    # Look up the real method on the class; mock/proxy dynamic attributes must
    # not manufacture an unrelated client and drop configured responses.
    with_options = getattr(type(client), "with_options", None)
    return client.with_options(max_retries=0) if callable(with_options) else client


def tracked_sync_completion(client, *, purpose, provider, retries=0, **kwargs):
    request_client = _without_sdk_retry(client)
    retries = max(0, min(int(retries), 3))
    for attempt in range(1, retries + 2):
        call = begin_call(purpose, provider, kwargs["model"], attempt)
        try:
            response = request_client.chat.completions.create(**kwargs)
        except Exception as error:
            finish_call(call, error=error, response=getattr(error, "response", None))
            if attempt <= retries and _retryable(error):
                time.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
                continue
            raise
        finish_call(call, response=response)
        return response, call["id"]


class TrackedStream:
    def __init__(self, stream, call):
        self.stream, self.call = stream, call
        self.usage = None
        self.reason = None
        self.response_id = None
        self.error = None
        self.exhausted = False

    async def __aenter__(self):
        try:
            await self.stream.__aenter__()
        except BaseException as error:
            await run_in_threadpool(finish_call, self.call, error=error,
                                    cancelled=isinstance(error, asyncio.CancelledError))
            raise
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self.stream.__anext__()
        except StopAsyncIteration:
            self.exhausted = True
            raise
        except BaseException as error:
            self.error = error
            raise
        if getattr(chunk, "usage", None) is not None:
            self.usage = chunk.usage
        if getattr(chunk, "id", None):
            self.response_id = chunk.id
        for choice in getattr(chunk, "choices", None) or []:
            if getattr(choice, "finish_reason", None) is not None:
                self.reason = choice.finish_reason
        return chunk

    async def __aexit__(self, exc_type, exc, traceback):
        try:
            return await self.stream.__aexit__(exc_type, exc, traceback)
        except BaseException as error:
            self.error = error
            raise
        finally:
            error = exc or self.error
            await asyncio.shield(run_in_threadpool(
                finish_call, self.call, usage=self.usage, finish_reason=self.reason,
                response_id=self.response_id,
                response=getattr(self.stream, "response", None),
                error=error, cancelled=isinstance(error, (asyncio.CancelledError, GeneratorExit))
                or (not self.exhausted and error is None),
            ))


async def tracked_async_completion(client, *, purpose, provider, **kwargs):
    request_client = _without_sdk_retry(client)
    retries = max(0, min(int(settings.LLM_MAX_RETRIES), 3))
    for attempt in range(1, retries + 2):
        call = await run_in_threadpool(begin_call, purpose, provider, kwargs["model"], attempt)
        try:
            response = await request_client.chat.completions.create(**kwargs)
        except BaseException as error:
            await asyncio.shield(run_in_threadpool(
                finish_call, call, error=error, response=getattr(error, "response", None),
                cancelled=isinstance(error, asyncio.CancelledError),
            ))
            if attempt <= retries and _retryable(error):
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
                continue
            raise
        if kwargs.get("stream"):
            return TrackedStream(response, call), call["id"]
        await run_in_threadpool(finish_call, call, response=response)
        return response, call["id"]
