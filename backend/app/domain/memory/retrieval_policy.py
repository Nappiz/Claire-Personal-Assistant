from __future__ import annotations
import logging
import re
from app.domain.memory.contracts import MEMORY_RECALL_RE, SEARCH_STOPWORDS
logger = logging.getLogger("services.memory_service")

class RetrievalPolicy:
    def __init__(self, config):
        self.config = config

    def is_standalone_assistant_question(self, user_message: str) -> bool:
        """Identify questions about Claire's general identity, not user memory."""
        normalized = " ".join(user_message.lower().split())
        refers_to_claire = bool(re.search(r"\b(kamu|mu|lo|claire)\b", normalized))
        asks_about_creator = bool(
            re.search(r"\b(siapa|apa)\b.*\b(nyiptain|menciptakan|pencipta)\b", normalized)
            or re.search(r"\b(siapa|apa)\b.*\b(bikin|buat)\s+(?:kamu|claire)\s*\??$", normalized)
        )
        asks_general_identity = bool(re.search(r"\b(kamu|claire)\s+(?:itu\s+)?(?:siapa|apa)\b", normalized))
        return refers_to_claire and (asks_about_creator or asks_general_identity)

    def memory_intent_keywords(self, user_message: str) -> list[str]:
        """Add deterministic relation hints for common personal-memory questions.

    The LLM router often reduces Indonesian questions such as ``aku kerja di
    mana`` to only ``nafiz``. Every fact sourced by Nafiz then has the same
    lexical score and the desired relation can fall outside Neo4j's per-keyword
    limit. Relation hints use the normalized Cypher relationship names, so the
    intended fact gets its own exact lookup.
    """
        normalized = " ".join(str(user_message or "").lower().split())
        relation_rules = (
            (r"\b(pacar(?:ku|nya)?|pasangan(?:ku|nya)?|jadian|dating)\b", ["dating", "dating since"]),
            (r"\b(kerja|bekerja|magang|kantor|pekerjaan(?:ku|nya)?)\b", ["works at", "works as"]),
            (r"\b(tanggal lahir|lahir|ulang tahun|ultah)\b", ["born on", "born in"]),
            (r"\b(kuliah|kampus|mahasiswa|jurusan|semester)\b", ["studied at"]),
            (r"\b(rumah(?:ku|nya)?|tinggal|domisili)\b", ["lives in"]),
            (r"\b(asal|berasal)\b", ["originates from"]),
            (r"\b(suka|favorit|kesukaan)\b", ["likes"]),
            (r"\b(alergi)\b", ["allergic to"]),
            (r"\b(punya|memiliki|milik)\b", ["owns"]),
        )
    
        hints: list[str] = []
        for pattern, relation_keywords in relation_rules:
            if re.search(pattern, normalized):
                hints.extend(relation_keywords)
    
        refers_to_user = bool(
            re.search(r"\b(aku|saya|gw|gue|nafiz|ku)\b", normalized)
            or re.search(r"\b(pacarku|pasanganku|pekerjaanku|rumahku)\b", normalized)
        )
        if not refers_to_user:
            return []
        if hints:
            hints.append("nafiz")
        return hints

    def requires_personal_memory(self, user_message: str) -> bool:
        normalized = " ".join(str(user_message or "").lower().split())
        return bool(MEMORY_RECALL_RE.search(normalized) or self.memory_intent_keywords(normalized))

    def local_search_keywords(self, user_message: str) -> list[str]:
        """Produce a useful graph query even if the LLM router is unavailable."""
        normalized = " ".join(str(user_message or "").lower().split())
        keywords = list(self.memory_intent_keywords(normalized))
        if re.search(r"\b(aku|saya|gw|gue|ku)\b", normalized):
            keywords.append("nafiz")
        for token in re.findall(r"[a-zA-Z0-9_-]+", normalized):
            if len(token) >= 3 and token not in SEARCH_STOPWORDS:
                keywords.append(token)
    
        deduplicated: list[str] = []
        for keyword in keywords:
            clean_keyword = " ".join(keyword.lower().split())[:100]
            if clean_keyword and clean_keyword not in deduplicated:
                deduplicated.append(clean_keyword)
        return deduplicated[:8]
