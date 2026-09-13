import logging
import uuid
from datetime import datetime, timezone
from app.domain.graph.fact_policy import validate_extracted_knowledge

from .write_event import GraphWriteEvent
from .entity_writes import EntityWrites
from .fact_writes import FactWrites
from .retractions import Retractions

class GraphWrites(EntityWrites, FactWrites, Retractions):
    def merge_knowledge(
        self,
        nodes: list[dict],
        edges: list[dict],
        retractions: list[dict] | None = None,
        source_conversation_id: str | None = None,
        source_message_id: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        event_id: str | None = None,
        event_at: datetime | None = None,
    ) -> dict:
        """Apply one extracted memory event atomically and in event-time order."""
        validated = validate_extracted_knowledge(
            {"nodes": nodes, "edges": edges, "retractions": retractions or []}
        )
        nodes = validated["nodes"]
        edges = validated["edges"]
        retractions = validated.get("retractions", [])
        stable_event_id = str(event_id or source_message_id or uuid.uuid4())
        stable_event_at = event_at or datetime.now(timezone.utc)
        if stable_event_at.tzinfo is None:
            stable_event_at = stable_event_at.replace(tzinfo=timezone.utc)
        event_at_ms = int(stable_event_at.timestamp() * 1000)
        scope_key = str(project_id or "").strip() or "global"

        def apply(tx):
            invalidated: set[str] = set()
            event = GraphWriteEvent(project_id, project_name, source_conversation_id,
                                    source_message_id, stable_event_id, event_at_ms, scope_key)
            entities_by_ref, refs_by_legacy_name = self._write_entities(tx, nodes, event, invalidated)
            def resolve_ref(raw: object) -> str | None:
                value = str(raw or "").strip()
                if value in entities_by_ref:
                    return value
                candidates = refs_by_legacy_name.get(self._clean_name(value), [])
                return candidates[0] if len(candidates) == 1 else None
            self._write_facts(tx, edges, event, invalidated, entities_by_ref, resolve_ref)
            self._apply_retractions(tx, retractions, event, invalidated, entities_by_ref, resolve_ref)
            return {"invalidated_source_message_ids": sorted(invalidated)}

        with self.driver.session() as session:
            if hasattr(session, "execute_write"):
                return session.execute_write(apply)
            return apply(session)
