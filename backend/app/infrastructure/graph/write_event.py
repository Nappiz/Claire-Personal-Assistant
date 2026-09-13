from dataclasses import dataclass

@dataclass(frozen=True)
class GraphWriteEvent:
    project_id: str | None
    project_name: str | None
    source_conversation_id: str | None
    source_message_id: str | None
    stable_event_id: str
    event_at_ms: int
    scope_key: str
