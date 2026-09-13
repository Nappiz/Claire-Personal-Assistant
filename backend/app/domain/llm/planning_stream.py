"""Assemble streamed assistant/tool deltas without depending on a provider SDK."""
from copy import deepcopy
from types import SimpleNamespace


def _plain(value):
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, SimpleNamespace):
        return _plain(vars(value))
    return value


def _merge_metadata(target, source):
    # Opaque provider extensions (including thought signatures) are values,
    # not text deltas: preserve them exactly, never concatenate or invent them.
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_metadata(target[key], value)
        else:
            target[key] = deepcopy(value)


class StreamedToolCall:
    def __init__(self, payload):
        self.payload = payload
        self.id = payload.get("id", "")
        self.function = SimpleNamespace(**payload.get("function", {}))

    def model_dump(self, *, exclude_none=False):
        return deepcopy(self.payload)


class PlanningStreamResult:
    def __init__(self):
        self.content = ""
        self.refusal = ""
        self.finish_reason = None
        self.has_choice = False
        self.metadata = {}
        self.calls = {}

    def add_choice(self, choice, text, finish_reason):
        self.has_choice = True
        if finish_reason:
            self.finish_reason = finish_reason
        delta = getattr(choice, "delta", None)
        if delta is None:
            return
        payload = _plain(delta)
        self.content += text
        self.refusal += str(payload.get("refusal") or "")
        _merge_metadata(self.metadata, {
            key: value for key, value in payload.items()
            if key not in {"content", "refusal", "tool_calls", "role"}
        })
        for fragment in payload.get("tool_calls") or []:
            index = fragment.get("index")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise ValueError("Streamed tool call requires a non-negative index")
            call = self.calls.setdefault(index, {"id": "", "type": "function",
                                                "function": {"name": "", "arguments": ""}})
            call["id"] += str(fragment.get("id") or "")
            function = fragment.get("function") or {}
            for key in ("name", "arguments"):
                call["function"][key] += str(function.get(key) or "")
            _merge_metadata(call, {key: value for key, value in fragment.items()
                                   if key not in {"index", "id", "function"}})
            _merge_metadata(call["function"], {key: value for key, value in function.items()
                                               if key not in {"name", "arguments"}})

    @property
    def tool_calls(self):
        return [StreamedToolCall(self.calls[index]) for index in sorted(self.calls)]

    def model_dump(self, *, exclude_none=False):
        return {**deepcopy(self.metadata), "role": "assistant", "content": self.content,
                "tool_calls": [call.model_dump() for call in self.tool_calls]}
