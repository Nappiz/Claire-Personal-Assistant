"""Allowlisted operational metadata; never log prompts, memory text, or keys."""
import json
import logging
from app.observability.correlation import correlation

logger = logging.getLogger(__name__)
FIELDS = frozenset({"invocation_id", "provider", "model", "purpose", "prompt_version",
    "request_id", "session_id", "turn_id",
    "status", "latency_ms", "prompt_tokens", "completion_tokens", "total_tokens",
    "total_cost", "candidate_ids", "tool", "result_count", "job_id", "job_state"})


def emit_event(event, **metadata):
    try:
        payload = {key: value for key, value in metadata.items() if key in FIELDS}
        for key, value in correlation.get().items():
            if key in {"request_id", "session_id", "turn_id"}:
                if payload.get(key) is None:
                    payload[key] = value
        logger.info("%s %s", event, json.dumps(payload, default=str, ensure_ascii=False))
    except Exception:
        # An observability failure must not fail a completed operation.
        pass
