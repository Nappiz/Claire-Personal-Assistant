from __future__ import annotations
import logging
import re
from schemas.chat_sch import MemoryContext
from app.domain.llm.contracts import CONTEXT_REFERENCE_RE, GENERIC_ENTITY_REFERENCES
logger = logging.getLogger("services.llm_service")



class MemoryQueryPolicy:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    def reference_context(self, history: list | None, summary: str | None, current_message: str | None = None) -> dict:
        """Bound discourse context; it supplies antecedents, never new answer facts."""
        recent = []
        remaining = 6000
        for item in reversed(list(history or [])[-12:]):
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "")[-min(1500, remaining):]
            if content:
                recent.append({"role": item["role"], "content": content})
                remaining -= len(content)
            if remaining <= 0:
                break
        return {"history": list(reversed(recent)), "summary": str(summary or "")[-3000:],
                "current_message": str(current_message or "")[:6000]}

    def reference_matches(self, text: str) -> list:
        matches = []
        for match in CONTEXT_REFERENCE_RE.finditer(text):
            if match.group().casefold() == "nya":
                # These suffixes introduce a name or complete a predicate. They
                # must not require an extra antecedent alongside an explicit name.
                before = text[:match.start()].casefold()
                if re.search(r"(?:\bnama|\btinggal\s*|\bdomisili\s*)$", before):
                    continue
            matches.append(match)
        return matches

    def inline_person_reference(self, text: str) -> str | None:
        """Resolve narrowly explicit local bindings, not proximity between names."""
        patterns = (
            r"\b(?:teman|temen|teman aku|temen aku|teman saya|temen saya)(?:ku)?\s+(?:namanya|bernama)\s+([\w'-]+(?:\s+[\w'-]+){0,2}?)\s*[,;]?\s+dia\b",
            r"\bsi\s+([\w'-]+)\s+(?:itu\s+)?dia\b",
        )
        names = [match.group(1) for pattern in patterns for match in re.finditer(pattern, text, re.IGNORECASE)]
        if len({name.casefold() for name in names}) != 1:
            return None
        name = names[0]
        if any(word.casefold() in GENERIC_ENTITY_REFERENCES | {"dan", "atau", "aku", "saya"} for word in name.split()):
            return None
        # A second explicit subject before another pronoun needs clause-specific
        # resolution; a global replacement cannot safely represent that turn.
        if len(re.findall(r"\b(?:dia|ia|beliau)\b", text, re.IGNORECASE)) > 1:
            tail = text[re.search(r"\bdia\b", text, re.IGNORECASE).end():]
            if re.search(r"\b(?:dan|sedangkan|sementara|tapi)\s+(?:si\s+)?[\w'-]+\s+(?:itu\s+)?dia\b", tail, re.IGNORECASE):
                return None
        return name

    def reference_clarification(self, context: MemoryContext) -> str | None:
        if context.query_resolution.status != "ambiguous":
            return None
        candidates = context.query_resolution.candidates
        return ("Yang kamu maksud " + " atau ".join(candidates[:3]) + "?" if candidates
                else "Yang kamu maksud siapa atau yang mana?")
