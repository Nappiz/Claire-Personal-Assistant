import logging

logger = logging.getLogger(__name__)
from .write_event import GraphWriteEvent

class EntityWrites:
    def _write_entities(self, tx, nodes, event: GraphWriteEvent, invalidated):
        project_id = event.project_id
        project_name = event.project_name
        source_conversation_id = event.source_conversation_id
        source_message_id = event.source_message_id
        stable_event_id = event.stable_event_id
        event_at_ms = event.event_at_ms
        scope_key = event.scope_key
        project_entity_key = None
        if project_id:
            project_entity_key = f"project:{project_id}"
            tx.run(
                """
                MERGE (p:Entity:Project {entity_key: $entity_key})
                ON CREATE SET p.created_at = timestamp(), p.importance = 1.0
                SET p.name = $name, p.display_name = $display_name,
                    p.project_id = $project_id, p.updated_at = timestamp()
                """,
                entity_key=project_entity_key,
                name=self._clean_name(project_name or project_id),
                display_name=str(project_name or project_id).strip(),
                project_id=project_id,
            )

        entities_by_ref: dict[str, dict] = {}
        refs_by_legacy_name: dict[str, list[str]] = {}
        for index, node in enumerate(nodes):
            label = self._clean_label(node.get("label", "Entity"))
            name = self._clean_name(node.get("name", ""))
            if not name:
                continue
            identity_context = self._clean_name(node.get("identity_context", ""))
            identity_signature = self._canonical_identity_context(identity_context)
            is_active_project = bool(
                project_entity_key
                and label.lower() == "project"
                and (
                    identity_context == self._clean_name(project_id)
                    or name in {
                        self._clean_name(project_id),
                        self._clean_name(project_name or project_id),
                    }
                )
            )
            entity_key = (
                project_entity_key
                if is_active_project
                else self._entity_key(label, name, identity_context)
            )
            identity_key = None
            if label.lower() == "person" and name not in {"nafiz", "claire"}:
                identity_key = entity_key
                # The registry lock serializes linking decisions for this
                # identity. Its relationship survives display-name/key edits.
                linked = tx.run(
                    """
                    MERGE (i:EntityIdentity {identity_key: $identity_key})
                    ON CREATE SET i.name = $name, i.canonical_context = $identity_signature,
                                  i.created_at = timestamp()
                    SET i.write_fence = $event_id, i.updated_at = timestamp()
                    WITH i
                    OPTIONAL MATCH (i)-[:RESOLVES_TO]->(person:Entity:Person)
                    RETURN collect(person.entity_key) AS linked_keys
                    """,
                    identity_key=identity_key, name=name,
                    identity_signature=identity_signature, event_id=stable_event_id,
                ).single()
                linked_keys = [key for key in (linked or {}).get("linked_keys", []) if key]
                if not linked_keys:
                    candidates = tx.run(
                        """
                        MATCH (person:Entity:Person {name: $name})
                        RETURN person.entity_key AS entity_key,
                               person.identity_context AS identity_context,
                               person.identity_signature AS identity_signature
                        ORDER BY person.entity_key
                        LIMIT 51
                        """,
                        name=name,
                    )
                    matching_keys = []
                    candidate_count = 0
                    for candidate in candidates:
                        candidate_count += 1
                        signature = candidate.get("identity_signature") or self._canonical_identity_context(
                            candidate.get("identity_context", "")
                        )
                        if signature == identity_signature and candidate.get("entity_key"):
                            matching_keys.append(candidate["entity_key"])
                    linked_keys = sorted(set(matching_keys))
                    # A truncated candidate set cannot prove uniqueness.
                    if candidate_count >= 51:
                        linked_keys.append("candidate_budget_exceeded")
                if len(linked_keys) > 1 or "candidate_budget_exceeded" in linked_keys:
                    tx.run(
                        """
                        MATCH (i:EntityIdentity {identity_key: $identity_key})
                        SET i.review_status = 'pending_ambiguous',
                            i.candidate_entity_keys = $candidate_keys
                        """,
                        identity_key=identity_key, candidate_keys=linked_keys,
                    )
                    if source_message_id:
                        invalidated.add(str(source_message_id))
                    logger.warning("Quarantining ambiguous Person identity %s", identity_key)
                    continue
                if linked_keys:
                    entity_key = linked_keys[0]
            node_ref = str(node.get("id") or f"__legacy_node_{index}").strip()
            if not node_ref or node_ref in entities_by_ref:
                continue
            tx.run(
                f"""
                MERGE (n:Entity {{entity_key: $entity_key}})
                ON CREATE SET n.created_at = timestamp(), n.importance = 1.0,
                              n.source_conversation_id = $source_conversation_id,
                              n.source_message_id = $source_message_id
                SET n:{label}, n.name = $name, n.display_name = $name,
                    n.identity_context = $identity_context,
                    n.identity_signature = $identity_signature,
                    n.identity_aliases = CASE
                        WHEN $identity_context IS NULL OR $identity_context IN coalesce(n.identity_aliases, [])
                        THEN coalesce(n.identity_aliases, [])
                        ELSE coalesce(n.identity_aliases, []) + [$identity_context] END,
                    n.updated_at = timestamp(),
                    n.importance = CASE WHEN
                        ($source_message_id IS NOT NULL AND $source_message_id IN coalesce(n.source_message_ids, []))
                        OR ($source_message_id IS NULL AND n.last_applied_event_id = $event_id)
                        OR $event_at < coalesce(n.latest_event_at, 0)
                        THEN coalesce(n.importance, 1.0) ELSE coalesce(n.importance, 1.0) + 0.5 END,
                    n.last_applied_event_id = $event_id,
                    n.latest_event_at = CASE WHEN $event_at >= coalesce(n.latest_event_at, 0)
                        THEN $event_at ELSE n.latest_event_at END,
                    n.source_conversation_id = coalesce(n.source_conversation_id, $source_conversation_id),
                    n.source_message_id = coalesce(n.source_message_id, $source_message_id),
                    n.last_source_conversation_id = coalesce($source_conversation_id, n.last_source_conversation_id),
                    n.last_source_message_id = coalesce($source_message_id, n.last_source_message_id),
                    n.source_conversation_ids = CASE
                        WHEN $source_conversation_id IS NULL OR $source_conversation_id IN coalesce(n.source_conversation_ids, [])
                        THEN coalesce(n.source_conversation_ids, [])
                        ELSE coalesce(n.source_conversation_ids, []) + [$source_conversation_id] END,
                    n.source_message_ids = CASE
                        WHEN $source_message_id IS NULL OR $source_message_id IN coalesce(n.source_message_ids, [])
                        THEN coalesce(n.source_message_ids, [])
                        ELSE coalesce(n.source_message_ids, []) + [$source_message_id] END
                """,
                entity_key=entity_key,
                name=name,
                identity_context=identity_context or None,
                identity_signature=identity_signature or None,
                source_conversation_id=source_conversation_id,
                source_message_id=source_message_id,
                event_id=stable_event_id,
                event_at=event_at_ms,
            )
            if identity_key:
                tx.run(
                    """
                    MATCH (i:EntityIdentity {identity_key: $identity_key})
                    MATCH (person:Entity {entity_key: $entity_key})
                    MERGE (i)-[:RESOLVES_TO]->(person)
                    SET i.review_status = 'approved', i.candidate_entity_keys = [],
                        i.identity_aliases = CASE
                            WHEN $identity_context IN coalesce(i.identity_aliases, [])
                            THEN coalesce(i.identity_aliases, [])
                            ELSE coalesce(i.identity_aliases, []) + [$identity_context] END
                    """,
                    identity_key=identity_key, entity_key=entity_key,
                    identity_context=identity_context,
                )
            entities_by_ref[node_ref] = {
                "entity_key": entity_key,
                "name": name,
                "confidence": float(node.get("confidence", 1.0)),
            }
            refs_by_legacy_name.setdefault(name, []).append(node_ref)
            if project_entity_key and label != "Project":
                tx.run(
                    """
                    MATCH (n:Entity {entity_key: $entity_key})
                    MATCH (p:Entity:Project {entity_key: $project_entity_key})
                    MERGE (n)-[r:BELONGS_TO {scope_key: $scope_key}]->(p)
                    ON CREATE SET r.fact_id = randomUUID(), r.created_at = timestamp()
                    SET r.is_current = true, r.review_status = 'approved',
                        r.memory_kind = 'scope', r.project_id = $project_id,
                        r.scope = 'project', r.updated_at = timestamp(),
                        r.source_conversation_ids = CASE
                            WHEN $source_conversation_id IS NULL OR $source_conversation_id IN coalesce(r.source_conversation_ids, [])
                            THEN coalesce(r.source_conversation_ids, [])
                            ELSE coalesce(r.source_conversation_ids, []) + [$source_conversation_id] END,
                        r.source_message_ids = CASE
                            WHEN $source_message_id IS NULL OR $source_message_id IN coalesce(r.source_message_ids, [])
                            THEN coalesce(r.source_message_ids, [])
                            ELSE coalesce(r.source_message_ids, []) + [$source_message_id] END
                    """,
                    entity_key=entity_key,
                    project_entity_key=project_entity_key,
                    scope_key=scope_key,
                    project_id=project_id,
                    source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id,
                )

        return entities_by_ref, refs_by_legacy_name
