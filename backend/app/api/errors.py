import logging
from openai import APIConnectionError, APIStatusError, APITimeoutError
from app.domain.diagnostics import InternalFeatureError, redact_diagnostic_log
from app.infrastructure.legacy_bridges import llm_gateway as llm_service
def _upstream_error_payload(exc: Exception, session_id: str) -> dict:
    """Map provider failures to stable, frontend-safe error codes."""
    exception_name = type(exc).__name__.lower()
    if isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError) or "timeout" in exception_name:
        code = "UPSTREAM_TIMEOUT"
        message = "The LLM provider timed out before completing the response."
    elif isinstance(exc, APIConnectionError) or any(
        marker in exception_name
        for marker in ("connection", "connecterror", "readerror", "protocolerror", "endofstream")
    ):
        code = "UPSTREAM_CONNECTION_ERROR"
        message = "The connection to the LLM provider was interrupted."
    elif isinstance(exc, APIStatusError):
        code = "UPSTREAM_HTTP_ERROR"
        message = f"The LLM provider rejected the request (HTTP {exc.status_code})."
    else:
        code = "UPSTREAM_ERROR"
        message = "The LLM stream ended unexpectedly."

    return {
        "type": "error",
        "session_id": session_id,
        "error": {"code": code, "message": message},
    }

def _is_llm_provider_error(exc: Exception) -> bool:
    """Keep provider/API failures on the existing model-failover path."""
    exception_name = type(exc).__name__.lower()
    return (
        isinstance(exc, (APIConnectionError, APIStatusError, APITimeoutError, TimeoutError))
        or any(
            marker in exception_name
            for marker in ("connection", "connecterror", "readerror", "protocolerror", "endofstream")
        )
        or str(exc) == "The upstream LLM returned an empty response"
    )

async def _internal_error_payload(
    exc: InternalFeatureError,
    session_id: str,
    *,
    model: str | None,
    provider: str | None,
) -> dict:
    """Build a terminal diagnostic event; analyzer failures never hide the log."""
    try:
        analysis = await llm_service.analyze_internal_error(
            operation=exc.operation,
            diagnostic_log=exc.diagnostic_log,
            model=model,
            provider=provider,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "The LLM diagnostic analysis was unavailable for %s",
            exc.operation,
            exc_info=True,
        )
        analysis = (
            "Aku mendeteksi kegagalan internal pada proses ini, tetapi analisis "
            "otomatisnya tidak tersedia. Detail teknis lengkapnya tetap tercantum di bawah."
        )

    return {
        "type": "internal_error",
        "session_id": session_id,
        "error": {
            "code": "INTERNAL_FEATURE_ERROR",
            "operation": exc.operation,
            "message": str(exc),
            "analysis": analysis,
            "log": redact_diagnostic_log(exc.diagnostic_log),
        },
    }
