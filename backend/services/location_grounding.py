"""Compatibility alias; remove after legacy policy consumers migrate (stage 8)."""
import sys
from app.domain.llm import location_grounding as implementation
sys.modules[__name__] = implementation
