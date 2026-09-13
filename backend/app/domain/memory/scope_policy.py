from __future__ import annotations
import logging
import re
logger = logging.getLogger("services.memory_service")

class ScopePolicy:
    def __init__(self, config):
        self.config = config

    def normalized_text(self, value: object) -> str:
        return " ".join(str(value or "").casefold().split())

    def mentions_project_name(self, text: str, project_name: str) -> bool:
        normalized_text = self.normalized_text(text)
        normalized_name = self.normalized_text(project_name)
        if not normalized_name:
            return False
        return bool(
            re.search(
                rf"(?<!\w){re.escape(normalized_name)}(?!\w)",
                normalized_text,
                flags=re.UNICODE,
            )
        )
