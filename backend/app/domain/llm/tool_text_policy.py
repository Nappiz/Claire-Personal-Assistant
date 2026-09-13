"""Keep provider textual tool envelopes out of visible assistant responses."""
import ast
import json
import re
from dataclasses import dataclass


_TEXT_TOOLS = ("web_search", "read_url")


def _tool_body(text):
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        if body.endswith("```"):
            body = body[:-3]
        body = body.strip()
    elif body.startswith("`"):
        body = body[1:]
        if body.endswith("`"):
            body = body[:-1]
        body = body.strip()
    return body


def _function_envelope(body):
    # Only literal keyword arguments on an allowlisted bare name. Never eval.
    if len(body) > 32768:
        return None
    try:
        call = ast.parse(body, mode="eval").body
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                or call.func.id not in _TEXT_TOOLS or call.args):
            return None
        arguments = {}
        for keyword in call.keywords:
            if keyword.arg is None or keyword.arg in arguments:
                return None
            arguments[keyword.arg] = ast.literal_eval(keyword.value)
    except (ValueError, SyntaxError, TypeError, RecursionError):
        return None
    if call.func.id == "web_search":
        if not arguments.keys() <= {"query", "queries", "research_goal", "time_range"}:
            return None
        if "query" in arguments:
            if "queries" in arguments or not isinstance(arguments["query"], str):
                return None
            arguments["queries"] = [arguments.pop("query")]
        queries = arguments.get("queries")
        if (not isinstance(queries, list) or not queries
                or not all(isinstance(query, str) and query.strip() for query in queries)):
            return None
        if not isinstance(arguments.get("research_goal", ""), str):
            return None
        if arguments.get("time_range") not in (None, "day", "month", "year"):
            return None
    elif arguments.keys() != {"url"} or not isinstance(arguments["url"], str):
        return None
    return {"action": call.func.id, "action_input": arguments}


def tool_envelope(text):
    body = _tool_body(text)
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return _function_envelope(body)
    if not isinstance(payload, dict):
        return None
    if "action" in payload and "action_input" in payload:
        return payload
    if payload.get("name") in {"web_search", "read_url"} and "arguments" in payload:
        return {"action": payload["name"], "action_input": payload["arguments"],
                "research_goal": payload.get("research_goal", "")}
    return None


def looks_like_tool_text(text):
    return (bool(re.match(r"(?:web_search|read_url)\s*\(", _tool_body(text)))
            or tool_envelope(text) is not None or bool(re.search(
                r'"(?:action|name)"\s*:\s*"(?:web_search|read_url)"', text)))


def _possible_function_prefix(beginning):
    for name in _TEXT_TOOLS:
        if name.startswith(beginning):
            return True
        if beginning.startswith(name):
            tail = beginning[len(name):].lstrip()
            if not tail or tail.startswith("("):
                return True
    return False


@dataclass
class PlanningProtocolError(Exception):
    reason: str
    search_plan: object = None

    def __str__(self):
        return self.reason


class VisibleTextGate:
    """Stream prose once its prefix cannot be JSON or a textual tool call."""
    def __init__(self):
        self.pending = ""
        self.prose = False

    def feed(self, text):
        if self.prose:
            return text
        self.pending += text
        beginning = self.pending.lstrip()
        if (not beginning or beginning[0] in "{[`"
                or _possible_function_prefix(beginning)):
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
