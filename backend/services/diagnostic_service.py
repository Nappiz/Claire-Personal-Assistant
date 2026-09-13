"""Compatibility alias; remove after roadmap stage 8."""
import sys
from app.domain import diagnostics
sys.modules[__name__] = diagnostics
