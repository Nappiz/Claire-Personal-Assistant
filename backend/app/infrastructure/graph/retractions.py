import logging
from configs.settings import settings
from app.domain.graph.fact_policy import normalize_relation

from .write_event import GraphWriteEvent

class Retractions:
    def _apply_retractions(self, tx, retractions, event: GraphWriteEvent, invalidated, entities_by_ref, resolve_ref):
        project_id = event.project_id
        project_name = event.project_name
        source_conversation_id = event.source_conversation_id
        source_message_id = event.source_message_id
        stable_event_id = event.stable_event_id
        event_at_ms = event.event_at_ms
        scope_key = event.scope_key
        for retraction in retractions:
            relation_name = normalize_relation(retraction.get("relation", "RELATED_TO"))
            source_ref = resolve_ref(retraction.get("source"))
            target_ref = resolve_ref(retraction.get("target")) if retraction.get("target") else None
            if source_ref is None:
                continue
            if retraction.get("target") and target_ref is None:
                continue
            retraction_confidence = min(
                float(retraction.get("confidence", 1.0)),
                entities_by_ref[source_ref]["confidence"],
                entities_by_ref[target_ref]["confidence"] if target_ref else 1.0,
            )
            if retraction_confidence < settings.MEMORY_FACT_CONFIDENCE_THRESHOLD:
                if source_message_id:
                    invalidated.add(str(source_message_id))
                continue
            source = entities_by_ref[source_ref]["entity_key"]
            target_key = entities_by_ref[target_ref]["entity_key"] if target_ref else None
            # Retire-before-write must survive an older job arriving later.
            # Fact-ID-specific retractions retain their existing narrow scope.
            if relation_name == "LIVES_IN" and not retraction.get("fact_id"):
                tx.run("MATCH (a:Entity {entity_key: $source}) SET a.memory_write_fence = $event_id",
                       source=source, event_id=stable_event_id)
                tx.run(
                    """MERGE (m:ResidenceRetraction {marker_key: $marker_key})
                    ON CREATE SET m.created_at = timestamp()
                    SET m.source_key = $source, m.target_key = $target, m.scope_key = $scope_key,
                        m.event_id = CASE WHEN $event_at >= coalesce(m.event_at, 0) THEN $event_id ELSE m.event_id END,
                        m.event_at = CASE WHEN $event_at >= coalesce(m.event_at, 0) THEN $event_at ELSE m.event_at END,
                        m.updated_at = timestamp()""",
                    marker_key=self._residence_marker_key(source, scope_key, target_key),
                    source=source, target=target_key, scope_key=scope_key,
                    event_at=event_at_ms, event_id=stable_event_id,
                )
            rows = tx.run(
                f"""
                MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->(b:Entity)
                WHERE coalesce(old.scope_key, 'global') = $scope_key
                  AND coalesce(old.is_current, true) = true
                  AND CASE WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                      THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END <= $event_at
                  AND ($fact_id IS NULL OR old.fact_id = $fact_id)
                  AND ($target IS NULL OR b.entity_key = $target)
                SET old.is_current = false, old.retracted_at = $event_at,
                    old.retracted_by_event_id = $event_id,
                    old.lifecycle_event_at = $event_at, old.updated_at = timestamp()
                RETURN coalesce(old.source_message_ids, []) +
                       CASE WHEN old.source_message_id IS NULL THEN [] ELSE [old.source_message_id] END AS source_message_ids
                """,
                source=source, target=target_key,
                fact_id=retraction.get("fact_id"), scope_key=scope_key,
                event_at=event_at_ms, event_id=stable_event_id,
            )
            retracted_any = False
            for row in rows:
                retracted_any = True
                invalidated.update(str(v) for v in (row.get("source_message_ids") or []) if v)
            if not retracted_any and source_message_id:
                invalidated.add(str(source_message_id))
