from dataclasses import dataclass
import re
ERROR_FALLBACK_MSG = "Aduh, otakku lagi ngeblank sebentar nih. Nanti ngobrol lagi ya!"

DEFAULT_MODEL_NAME = "gemini-3.1-flash-lite"

CONTEXT_REFERENCE_RE = re.compile(
    r"\b(?:dia|ia|beliau|mereka|nya|orang itu|yang tadi|proyek itu|project itu|"
    r"he|she|him|her|his|they|them|their|(?-i:it|its|It|Its))\b|(?<=\w)nya\b", re.IGNORECASE
)

GENERIC_ENTITY_REFERENCES = {
    "dia", "ia", "nya", "beliau", "mereka", "orangnya", "seseorang",
    "orang itu", "temannya", "temenku", "temen nya",
}

QUESTION_CLAUSE_RE = re.compile(
    r"\b(?:siapa|apa|apakah|kapan|berapa|dimana|di\s+mana|kenapa|mengapa|mana|"
    r"gimana|bagaimana|who|what|when|where|why|how|can\s+you|could\s+you|"
    r"do\s+you|did\s+you|is\s+it|are\s+you)\b",
    flags=re.IGNORECASE,
)

class MemoryLLMUnavailableError(RuntimeError):
    """All configured memory-intelligence providers failed."""

@dataclass(frozen=True)
class MemoryRouteDecision:
    status: str
    keywords: list[str]
    error: str | None = None
    query: str | None = None
    reference_status: str = "none"
    candidates: tuple[str, ...] = ()
    confidence: float = 0.0
