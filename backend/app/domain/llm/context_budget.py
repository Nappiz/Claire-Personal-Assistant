from __future__ import annotations
import logging
from schemas.chat_sch import MemoryContext
logger = logging.getLogger("services.llm_service")



class ContextBudget:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    def estimate_prompt_tokens(self, value: object) -> int:
        """Conservative provider-neutral estimate using encoded byte volume."""
        text = str(value or "")
        return max(1, (len(text.encode("utf-8")) + 1) // 2)

    def bounded_memory_items(self, memory_context: MemoryContext) -> tuple[list[dict], list[str]]:
        vector_items: list[dict] = []
        for raw in list(memory_context.qdrant_context or [])[:3]:
            item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
            item["content"] = str(item.get("content") or "")[:1_000]
            vector_items.append(item)
        graph_items = [str(item)[:500] for item in list(memory_context.neo4j_context or [])[:8]]
        return vector_items, graph_items

    def fit_history_to_prompt_budget(self, 
        system_prompt: str,
        user_message: str,
        session_history: list | None,
    ) -> list[dict]:
        budget = max(int(self.config.CHAT_INPUT_TOKEN_BUDGET), 4_000)
        used = self.estimate_prompt_tokens(system_prompt) + self.estimate_prompt_tokens(user_message) + 64
        selected: list[dict] = []
        for raw in reversed(list(session_history or [])):
            if not isinstance(raw, dict) or raw.get("role") not in {"user", "assistant"}:
                continue
            message = {"role": raw["role"], "content": str(raw.get("content") or "")[:12_000]}
            cost = self.estimate_prompt_tokens(message["content"]) + 8
            if used + cost > budget:
                continue
            selected.append(message)
            used += cost
        selected.reverse()
        return selected
