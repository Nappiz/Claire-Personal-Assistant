import logging
import uuid
from configs.settings import settings
from app.domain.graph.fact_policy import get_relation_policy, normalize_relation

logger = logging.getLogger(__name__)
from .write_event import GraphWriteEvent

class FactWrites:
    def _write_facts(self, tx, edges, event: GraphWriteEvent, invalidated, entities_by_ref, resolve_ref):
        project_id = event.project_id
        project_name = event.project_name
        source_conversation_id = event.source_conversation_id
        source_message_id = event.source_message_id
        stable_event_id = event.stable_event_id
        event_at_ms = event.event_at_ms
        scope_key = event.scope_key
        for edge in edges:
            source_ref = resolve_ref(edge.get("source"))
            target_ref = resolve_ref(edge.get("target"))
            relation_name = normalize_relation(edge.get("relation", "RELATED_TO"))
            if source_ref is None or target_ref is None:
                logger.warning("Skipping unknown graph endpoints for %s", relation_name)
                continue
            source = entities_by_ref[source_ref]["entity_key"]
            target = entities_by_ref[target_ref]["entity_key"]
            relation_policy = get_relation_policy(relation_name)
            proposed_fact_id = str(uuid.uuid4())
            supersedes = [str(item).strip() for item in edge.get("supersedes", []) if str(item).strip()]
            replaces_current_relation = edge.get("replaces_current_relation") is True
            confidence = min(
                float(edge.get("confidence", 1.0)),
                entities_by_ref[source_ref]["confidence"],
                entities_by_ref[target_ref]["confidence"],
            )

            tx.run(
                """
                MATCH (a:Entity {entity_key: $source})
                SET a.memory_write_fence = $event_id
                """,
                source=source,
                event_id=stable_event_id,
            )
            conflicting_fact_ids: list[str] = []
            newest_conflict_event = 0
            residence_retracted_at = 0
            if relation_name == "LIVES_IN":
                marker = tx.run(
                    """MATCH (m:ResidenceRetraction)
                    WHERE m.marker_key IN $marker_keys
                    RETURN coalesce(max(m.event_at), 0) AS retracted_event_at""",
                    marker_keys=[self._residence_marker_key(source, scope_key, target),
                                 self._residence_marker_key(source, scope_key)],
                ).single()
                residence_retracted_at = int((marker or {}).get("retracted_event_at") or 0)
            if relation_policy.cardinality == "one":
                record = tx.run(
                    f"""
                    MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->(other:Entity)
                    WHERE other.entity_key <> $target
                      AND coalesce(old.scope_key, 'global') = $scope_key
                      AND coalesce(old.is_current, true) = true
                      AND coalesce(old.review_status, 'approved') = 'approved'
                      AND (old.expires_at IS NULL OR old.expires_at > timestamp())
                    RETURN collect(old.fact_id) AS fact_ids,
                           coalesce(max(CASE
                               WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                               THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END), 0) AS newest_event_at
                    """,
                    source=source,
                    target=target,
                    scope_key=scope_key,
                ).single()
                if record:
                    conflicting_fact_ids = [str(v) for v in (record.get("fact_ids") or []) if v]
                    newest_conflict_event = int(record.get("newest_event_at") or 0)
            explicit_resolution = replaces_current_relation or bool(set(conflicting_fact_ids) & set(supersedes))
            if confidence < settings.MEMORY_FACT_CONFIDENCE_THRESHOLD:
                review_status = "pending_low_confidence"
            elif newest_conflict_event > event_at_ms or (residence_retracted_at and residence_retracted_at >= event_at_ms):
                review_status = "pending_stale_event"
            elif conflicting_fact_ids and not explicit_resolution:
                review_status = "pending_conflict"
            else:
                review_status = "approved"
            approve_new_fact = review_status == "approved"
            if not approve_new_fact and source_message_id:
                invalidated.add(str(source_message_id))

            record = tx.run(
                f"""
                MATCH (a:Entity {{entity_key: $source}})
                MATCH (b:Entity {{entity_key: $target}})
                MERGE (a)-[r:{relation_name} {{scope_key: $scope_key}}]->(b)
                ON CREATE SET r.fact_id = $fact_id, r.created_at = timestamp(),
                              r.source_event_at = $event_at,
                              r.source_conversation_id = $source_conversation_id,
                              r.source_message_id = $source_message_id
                WITH a, b, r, NOT (
                    ($source_message_id IS NOT NULL AND $source_message_id IN coalesce(r.source_message_ids, []))
                    OR ($source_message_id IS NULL AND r.last_applied_event_id = $event_id)
                ) AS new_event,
                     $event_at >= CASE
                         WHEN coalesce(r.lifecycle_event_at, 0) > coalesce(r.source_event_at, 0)
                         THEN r.lifecycle_event_at ELSE coalesce(r.source_event_at, 0) END AS newest_event
                SET r.fact_id = coalesce(r.fact_id, $fact_id),
                    r.is_current = CASE WHEN newest_event THEN $approve_new_fact ELSE coalesce(r.is_current, true) END,
                    r.review_status = CASE WHEN newest_event THEN $review_status ELSE coalesce(r.review_status, 'approved') END,
                    r.confidence = CASE WHEN newest_event THEN $confidence ELSE coalesce(r.confidence, $confidence) END,
                    r.memory_kind = coalesce(r.memory_kind, $memory_kind),
                    r.observed_at = coalesce(r.observed_at, $event_at),
                    r.valid_from = coalesce(r.valid_from, $event_at),
                    r.expires_at = CASE WHEN newest_event AND $approve_new_fact AND $ttl_ms IS NOT NULL
                        THEN $event_at + $ttl_ms ELSE r.expires_at END,
                    r.last_confirmed_at = CASE WHEN newest_event AND $approve_new_fact
                        THEN $event_at ELSE coalesce(r.last_confirmed_at, r.created_at) END,
                    r.updated_at = timestamp(), r.scope = $scope, r.project_id = $project_id,
                    r.source_event_at = CASE WHEN newest_event THEN $event_at ELSE r.source_event_at END,
                    r.importance = CASE WHEN new_event AND newest_event AND $approve_new_fact
                        THEN coalesce(r.importance, 1.0) + 0.5 ELSE coalesce(r.importance, 1.0) END,
                    r.last_applied_event_id = $event_id,
                    r.superseded_at = CASE WHEN newest_event AND $approve_new_fact THEN null ELSE r.superseded_at END,
                    r.superseded_by = CASE WHEN newest_event AND $approve_new_fact THEN null ELSE r.superseded_by END,
                    r.source_conversation_id = coalesce(r.source_conversation_id, $source_conversation_id),
                    r.source_message_id = coalesce(r.source_message_id, $source_message_id),
                    r.last_source_conversation_id = coalesce($source_conversation_id, r.last_source_conversation_id),
                    r.last_source_message_id = coalesce($source_message_id, r.last_source_message_id),
                    r.source_conversation_ids = CASE
                        WHEN $source_conversation_id IS NULL OR $source_conversation_id IN coalesce(r.source_conversation_ids, [])
                        THEN coalesce(r.source_conversation_ids, []) ELSE coalesce(r.source_conversation_ids, []) + [$source_conversation_id] END,
                    r.source_message_ids = CASE
                        WHEN $source_message_id IS NULL OR $source_message_id IN coalesce(r.source_message_ids, [])
                        THEN coalesce(r.source_message_ids, []) ELSE coalesce(r.source_message_ids, []) + [$source_message_id] END,
                    a.importance = CASE WHEN new_event AND newest_event AND $approve_new_fact
                        THEN coalesce(a.importance, 1.0) + 0.1 ELSE coalesce(a.importance, 1.0) END,
                    b.importance = CASE WHEN new_event AND newest_event AND $approve_new_fact
                        THEN coalesce(b.importance, 1.0) + 0.1 ELSE coalesce(b.importance, 1.0) END
                RETURN r.fact_id AS fact_id
                """,
                source=source, target=target, fact_id=proposed_fact_id,
                source_conversation_id=source_conversation_id,
                source_message_id=source_message_id, approve_new_fact=approve_new_fact,
                review_status=review_status, confidence=confidence,
                memory_kind=relation_policy.kind, ttl_ms=relation_policy.ttl_milliseconds,
                scope_key=scope_key, scope="project" if project_id else "global",
                project_id=project_id, event_id=stable_event_id, event_at=event_at_ms,
            ).single()
            actual_fact_id = record["fact_id"] if record else proposed_fact_id
            old_ids = [item for item in supersedes if item != actual_fact_id]
            if approve_new_fact and old_ids:
                rows = tx.run(
                    f"""
                    MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->()
                    WHERE old.fact_id IN $old_fact_ids
                      AND coalesce(old.scope_key, 'global') = $scope_key
                      AND coalesce(old.is_current, true) = true
                      AND CASE WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                          THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END <= $event_at
                    SET old.is_current = false, old.superseded_at = $event_at,
                        old.superseded_by = $new_fact_id, old.lifecycle_event_at = $event_at,
                        old.updated_at = timestamp()
                    RETURN coalesce(old.source_message_ids, []) +
                           CASE WHEN old.source_message_id IS NULL THEN [] ELSE [old.source_message_id] END AS source_message_ids
                    """,
                    source=source, old_fact_ids=old_ids, new_fact_id=actual_fact_id,
                    scope_key=scope_key, event_at=event_at_ms,
                )
                for row in rows:
                    invalidated.update(str(v) for v in (row.get("source_message_ids") or []) if v)
            if approve_new_fact and replaces_current_relation:
                rows = tx.run(
                    f"""
                    MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->()
                    WHERE old.fact_id <> $new_fact_id
                      AND coalesce(old.scope_key, 'global') = $scope_key
                      AND coalesce(old.is_current, true) = true
                      AND CASE WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                          THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END <= $event_at
                    SET old.is_current = false, old.superseded_at = $event_at,
                        old.superseded_by = $new_fact_id, old.lifecycle_event_at = $event_at,
                        old.updated_at = timestamp()
                    RETURN coalesce(old.source_message_ids, []) +
                           CASE WHEN old.source_message_id IS NULL THEN [] ELSE [old.source_message_id] END AS source_message_ids
                    """,
                    source=source, new_fact_id=actual_fact_id,
                    scope_key=scope_key, event_at=event_at_ms,
                )
                for row in rows:
                    invalidated.update(str(v) for v in (row.get("source_message_ids") or []) if v)
