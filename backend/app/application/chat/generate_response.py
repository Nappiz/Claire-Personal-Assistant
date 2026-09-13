from __future__ import annotations
import logging
from schemas.chat_sch import MemoryContext
from app.domain.llm.contracts import DEFAULT_MODEL_NAME, ERROR_FALLBACK_MSG
logger = logging.getLogger("services.llm_service")

class GenerateResponse:
    def generate_chat_response(self, user_message: str, memory_context: MemoryContext, session_history: list = None, model: str = None, provider: str = None, session_summary: str | None = None) -> tuple[str, dict]:
        """
    Menyatukan system prompt, konteks dari memori, pesan history sesi, dan pesan user,
    kemudian mengirimkannya ke LLM yang dipilih via UI.
    """
        logger.info(f"Generating response from {provider} ({model})...")
        clarification = self.references.reference_clarification(memory_context)
        if clarification:
            return clarification, {}
        client = self.gateway.get_llm_client(provider)
        model_name = model or DEFAULT_MODEL_NAME
        llm_messages = self.prompts.build_chat_messages(user_message, memory_context, session_history, session_summary)

        try:
            response, invocation_id = self.gateway.tracked_sync_completion(
                client, purpose="chat", provider=provider, retries=self.config.LLM_MAX_RETRIES,
                model=model_name,
                messages=llm_messages,
                temperature=0.7,
                max_tokens=self.config.CHAT_OUTPUT_MAX_TOKENS,
            )

            usage = {
                **self.responses.usage_values(getattr(response, "usage", None)),
                "invocation_ids": [invocation_id],
                **{key: value for key, value in self.responses.completion_outcome({"finish_reasons": [
                    self.responses.finish_reason_text(getattr(response.choices[0], "finish_reason", None))
                ]}).items() if key != "type"},
            }

            return response.choices[0].message.content, usage
        except Exception as e:
            logger.error(f"Error calling LLM API ({provider}): {e}")
            return ERROR_FALLBACK_MSG, {}
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
