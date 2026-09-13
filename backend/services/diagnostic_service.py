"""Structured, redacted diagnostics for user-visible internal chat failures."""

from __future__ import annotations

import re
import traceback


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[:=]\s*)['\"]?[^'\"\s,;]+"),
    re.compile(r"\b(?:sk|gsk|AIza)[-_A-Za-z0-9]{12,}\b"),
)


def redact_diagnostic_log(value: str) -> str:
    """Remove credentials while preserving the complete diagnostic structure."""
    redacted = str(value or "")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted.replace("\x00", "")


def current_exception_log() -> str:
    """Capture the active traceback and redact credentials before persistence."""
    return redact_diagnostic_log(traceback.format_exc())


class InternalFeatureError(RuntimeError):
    """A non-LLM subsystem failure that must terminate the normal chat turn."""

    def __init__(self, operation: str, message: str, diagnostic_log: str):
        super().__init__(message)
        self.operation = operation
        self.diagnostic_log = redact_diagnostic_log(diagnostic_log)

    @classmethod
    def from_active_exception(cls, operation: str, message: str) -> "InternalFeatureError":
        return cls(operation, message, current_exception_log())

