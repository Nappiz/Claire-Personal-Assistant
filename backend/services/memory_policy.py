"""Compatibility alias; pure policies now belong to the graph domain."""
import sys
from app.domain.graph import fact_policy
sys.modules[__name__] = fact_policy
