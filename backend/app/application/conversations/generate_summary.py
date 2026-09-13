from __future__ import annotations
import logging
logger = logging.getLogger("services.llm_service")

class GenerateSummary:
    def generate_session_summary(self,
        existing_summary: str | None,
        messages_to_fold: list[dict],
    ) -> str:
        """Fold messages leaving the context window into a bounded rolling summary."""
        messages_json = self.prompts.safe_context_json(messages_to_fold)
        existing_json = self.prompts.safe_context_json({"summary": existing_summary or ""})
        prompt = f"""Ringkas kesinambungan percakapan untuk membantu turn berikutnya.
Jangan menambahkan fakta, asumsi, atau instruksi baru. Bedakan jelas ucapan user dan jawaban assistant.
Hasil maksimal 3500 karakter, berupa teks biasa. Ini hanya ringkasan percakapan, bukan sumber kebenaran fakta personal.

<existing_summary_json>{existing_json}</existing_summary_json>
<messages_json>{messages_json}</messages_json>"""
        try:
            response = self.gateway.memory_completion(
                purpose="summary",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1000,
            )
            summary = " ".join(response.choices[0].message.content.strip().split())
            return summary[:3500]
        except Exception:
            logger.exception("Could not update rolling session summary; using deterministic fallback")
            fallback_parts = [existing_summary.strip()] if existing_summary else []
            for item in messages_to_fold:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "unknown")
                content = " ".join(str(item.get("content") or "").split())
                if content:
                    fallback_parts.append(f"{role}: {content[:500]}")
            return " | ".join(fallback_parts)[-3500:]
