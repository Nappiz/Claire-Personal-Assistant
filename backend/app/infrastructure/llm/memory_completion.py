from __future__ import annotations
import logging
import time
from app.domain.llm.contracts import MemoryLLMUnavailableError
logger = logging.getLogger("services.llm_service")

class MemoryCompletion:
    def memory_llm_candidates(self) -> list[tuple[str, str]]:
        candidates = [(self.config.MEMORY_LLM_PROVIDER, self.config.MEMORY_LLM_MODEL)]
        if self.config.MEMORY_LLM_FALLBACK_PROVIDER and self.config.MEMORY_LLM_FALLBACK_MODEL:
            fallback = (self.config.MEMORY_LLM_FALLBACK_PROVIDER, self.config.MEMORY_LLM_FALLBACK_MODEL)
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def memory_completion(self, *, messages: list[dict], temperature: float, **kwargs):
        """Run internal memory intelligence with a configurable provider fallback."""
        client_timeout = float(kwargs.pop("client_timeout", self.config.MEMORY_LLM_TIMEOUT_SECONDS))
        purpose = kwargs.pop("purpose", "memory")
        deadline = time.monotonic() + max(client_timeout, 0.1)
        failures: list[str] = []
        for provider, model in self.memory_llm_candidates():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failures.append("memory LLM deadline exhausted")
                break
            client = None
            try:
                client = self.get_llm_client(
                    provider=provider,
                    timeout=max(remaining, 0.1),
                    max_retries=self.config.MEMORY_LLM_MAX_RETRIES,
                )
                response, _ = self.tracked_sync_completion(
                    client, purpose=purpose, provider=provider,
                    retries=self.config.MEMORY_LLM_MAX_RETRIES,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    **kwargs,
                )
                return response
            except Exception as exc:
                logger.warning("Memory LLM %s/%s failed: %s", provider, model, exc)
                failures.append(f"{provider}/{model}: {exc}")
            finally:
                if client is not None:
                    close_client = getattr(client, "close", None)
                    if callable(close_client):
                        try:
                            close_client()
                        except Exception:
                            logger.debug("Could not close memory LLM client cleanly", exc_info=True)
        raise MemoryLLMUnavailableError("; ".join(failures) or "No memory LLM configured")
