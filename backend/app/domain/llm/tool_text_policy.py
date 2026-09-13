"""Keep provider textual tool envelopes out of visible assistant responses."""
import json
import re
from dataclasses import dataclass


def tool_envelope(text):
    body = text.strip()
    if body.startswith("```") and body.endswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if "action" in payload and "action_input" in payload:
        return payload
    if payload.get("name") in {"web_search", "read_url"} and "arguments" in payload:
        return {"action": payload["name"], "action_input": payload["arguments"],
                "research_goal": payload.get("research_goal", "")}
    return None


def looks_like_tool_text(text):
    return tool_envelope(text) is not None or bool(re.search(
        r'"(?:action|name)"\s*:\s*"(?:web_search|read_url)"', text))


@dataclass
class PlanningProtocolError(Exception):
    reason: str
    search_plan: object = None

    def __str__(self):
        return self.reason


class VisibleTextGate:
    """Normal prose streams immediately; potential JSON is inspected first."""
    def __init__(self):
        self.pending = ""
        self.prose = False

    def feed(self, text):
        if self.prose:
            return text
        self.pending += text
        beginning = self.pending.lstrip()
        if not beginning or beginning[0] in "{[`":
            return ""
        self.prose = True
        pending, self.pending = self.pending, ""
        return pending

    def finish(self):
        if looks_like_tool_text(self.pending):
            self.pending = ""
            return ""
        pending, self.pending = self.pending, ""
        return pending
