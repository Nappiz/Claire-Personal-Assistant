"""Deprecated audit/test alias; implementation owned by page_reader."""
import sys
from app.infrastructure.web import page_reader
sys.modules[__name__] = page_reader
