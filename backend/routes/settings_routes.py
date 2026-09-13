"""Compatibility alias. Remove after legacy consumers migrate in stage 8."""
import sys
from app.api.routers import settings
sys.modules[__name__] = settings
