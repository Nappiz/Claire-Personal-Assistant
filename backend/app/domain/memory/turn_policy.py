class TurnPolicy:
    @staticmethod
    def normalize_completion(usage: dict, response_status: str, finish_reason: str | None):
        response_status = usage.get("response_status", response_status) if usage else response_status
        finish_reason = usage.get("finish_reason", finish_reason) if usage else finish_reason
        if str(finish_reason or "").lower() in {"length", "max_tokens", "max_output_tokens", "content_filter"}:
            response_status = "incomplete"
        if response_status not in {"complete", "incomplete"}:
            raise ValueError("Invalid AI response status")
        return response_status, finish_reason
