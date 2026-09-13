import logging


class GraphMutations:
    def delete_node(self, entity_key: str) -> dict | None:
        """Delete exactly one entity and its relationships by stable identity."""
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (n:Entity {entity_key: $entity_key})
                OPTIONAL MATCH (identity:EntityIdentity)-[:RESOLVES_TO]->(n)
                WITH n, collect(identity) AS identities, {
                    entity_key: n.entity_key,
                    name: n.name,
                    identity_context: n.identity_context
                } AS deleted
                FOREACH (identity IN identities | DETACH DELETE identity)
                DETACH DELETE n
                RETURN deleted
                """,
                entity_key=entity_key,
            ).single()
            return dict(record["deleted"]) if record else None

    def update_node(self, entity_key: str, updates: dict) -> dict | None:
        """Correct whitelisted entity properties without name-based targeting."""
        if not updates:
            raise ValueError("At least one node field must be supplied")

        allowed = {"name", "identity_context", "importance"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported node fields: {', '.join(sorted(unknown))}")
        if "importance" in updates and updates["importance"] is None:
            raise ValueError("Node importance cannot be null")

        with self.driver.session() as session:
            current = session.run(
                """
                MATCH (n:Entity {entity_key: $entity_key})
                RETURN n.name AS name, n.identity_context AS identity_context,
                       n.importance AS importance, labels(n) AS labels
                """,
                entity_key=entity_key,
            ).single()
            if not current:
                return None

            labels = current["labels"] or []
            label = next((item for item in labels if item != "Entity"), "Entity")
            new_name = self._clean_name(updates.get("name", current["name"]))
            if not new_name:
                raise ValueError("Node name cannot be empty")
            new_context = self._clean_name(
                updates.get("identity_context", current["identity_context"] or "")
            )
            identity_changed = "name" in updates or "identity_context" in updates
            new_entity_key = (
                self._entity_key(label, new_name, new_context)
                if identity_changed
                else entity_key
            )

            if new_entity_key != entity_key:
                conflict = session.run(
                    """
                    MATCH (n:Entity {entity_key: $new_entity_key})
                    RETURN count(n) AS count
                    """,
                    new_entity_key=new_entity_key,
                ).single()
                if conflict and conflict["count"]:
                    raise ValueError("The corrected identity already exists; refusing an implicit merge")

            importance = updates.get("importance", current["importance"] or 1.0)
            record = session.run(
                """
                MATCH (n:Entity {entity_key: $entity_key})
                SET n.entity_key = $new_entity_key,
                    n.name = $name,
                    n.display_name = $name,
                    n.identity_context = $identity_context,
                    n.identity_signature = $identity_signature,
                    n.importance = $importance,
                    n.updated_at = timestamp()
                RETURN n.entity_key AS entity_key, n.name AS name,
                       n.identity_context AS identity_context,
                       n.importance AS importance, labels(n) AS labels
                """,
                entity_key=entity_key,
                new_entity_key=new_entity_key,
                name=new_name,
                identity_context=new_context or None,
                identity_signature=self._canonical_identity_context(new_context) or None,
                importance=importance,
            ).single()
            return dict(record) if record else None

    def delete_fact(self, fact_id: str) -> dict | None:
        """Delete one relationship/fact while leaving both entities intact."""
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (source:Entity)-[r]->(target:Entity)
                WHERE r.fact_id = $fact_id
                WITH r, source.name AS source, target.name AS target,
                     type(r) AS relation, properties(r) AS properties,
                     coalesce(r.source_message_ids, []) +
                     CASE WHEN r.source_message_id IS NULL THEN [] ELSE [r.source_message_id] END AS source_message_ids
                DELETE r
                RETURN source, target, relation, properties, source_message_ids
                """,
                fact_id=fact_id,
            ).single()
            return dict(record) if record else None

    def update_fact(self, fact_id: str, updates: dict) -> dict | None:
        """Correct temporal/importance state for one relationship fact."""
        if not updates:
            raise ValueError("At least one fact field must be supplied")

        allowed = {"is_current", "importance"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported fact fields: {', '.join(sorted(unknown))}")
        if "is_current" in updates and updates["is_current"] is None:
            raise ValueError("Fact is_current cannot be null")
        if "importance" in updates and updates["importance"] is None:
            raise ValueError("Fact importance cannot be null")

        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (source:Entity)-[r]->(target:Entity)
                WHERE r.fact_id = $fact_id
                SET r.is_current = CASE
                        WHEN $set_is_current THEN $is_current
                        ELSE coalesce(r.is_current, true)
                    END,
                    r.importance = CASE
                        WHEN $set_importance THEN $importance
                        ELSE coalesce(r.importance, 1.0)
                    END,
                    r.last_confirmed_at = CASE
                        WHEN $set_is_current AND $is_current THEN timestamp()
                        ELSE r.last_confirmed_at
                    END,
                    r.superseded_at = CASE
                        WHEN $set_is_current AND NOT $is_current THEN timestamp()
                        WHEN $set_is_current AND $is_current THEN null
                        ELSE r.superseded_at
                    END,
                    r.superseded_by = CASE
                        WHEN $set_is_current AND $is_current THEN null
                        ELSE r.superseded_by
                    END,
                    r.review_status = CASE
                        WHEN $set_is_current AND $is_current THEN 'approved'
                        ELSE coalesce(r.review_status, 'approved')
                    END,
                    r.updated_at = timestamp()
                RETURN r.fact_id AS fact_id, source.name AS source,
                       target.name AS target, type(r) AS relation,
                       r.is_current AS is_current,
                       r.importance AS importance,
                       r.created_at AS created_at,
                       r.last_confirmed_at AS last_confirmed_at,
                       r.superseded_at AS superseded_at,
                       r.superseded_by AS superseded_by,
                       r.review_status AS review_status,
                       coalesce(r.source_message_ids, []) +
                       CASE WHEN r.source_message_id IS NULL THEN [] ELSE [r.source_message_id] END AS source_message_ids
                """,
                fact_id=fact_id,
                set_is_current="is_current" in updates,
                is_current=updates.get("is_current", True),
                set_importance="importance" in updates,
                importance=updates.get("importance", 1.0),
            ).single()
            return dict(record) if record else None
