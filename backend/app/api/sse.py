import json
def _sse_data(payload: dict) -> str:
    """Serialize one JSON payload as a standards-compliant SSE event."""
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"

STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

async def encode_events(events):
    async for event in events:
        yield _sse_data(event)
