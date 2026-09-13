"""Deprecated audit/test alias; telemetry has a single owner."""
import sys
from app.observability import ai_telemetry
sys.modules[__name__] = ai_telemetry
