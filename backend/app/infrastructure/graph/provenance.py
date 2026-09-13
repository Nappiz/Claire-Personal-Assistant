import logging

logger = logging.getLogger(__name__)

class GraphProvenance:
    def remove_conversation_provenance(
        self,
        conversation_id: str,
        message_ids: list[str] | None = None,
    ) -> dict:
        """Remove one deleted conversation's evidence from graph memory.

        Facts remain only when another conversation still supports them. Facts
        whose sole source was the deleted conversation are removed, and any
        newly orphaned entity is removed as well. This makes deleting a chat
        mean deleting the long-term memory derived exclusively from that chat.
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")

        source_message_ids = list({str(item) for item in (message_ids or []) if item})
        stats = {
            "relationships_unlinked": 0,
            "facts_deleted": 0,
            "nodes_unlinked": 0,
            "orphan_nodes_deleted": 0,
        }
        with self.driver.session() as session:
            relationship_cleanup = session.run(
                """
                MATCH ()-[r]->()
                WHERE r.source_conversation_id = $conversation_id
                   OR r.last_source_conversation_id = $conversation_id
                   OR $conversation_id IN coalesce(r.source_conversation_ids, [])
                WITH r,
                     [item IN coalesce(r.source_conversation_ids, [])
                      WHERE item <> $conversation_id] AS remaining_conversation_ids,
                     [item IN coalesce(r.source_message_ids, [])
                      WHERE NOT (item IN $source_message_ids)] AS remaining_message_ids
                SET r.source_conversation_ids = remaining_conversation_ids,
                    r.source_message_ids = remaining_message_ids,
                    r.source_conversation_id = CASE
                        WHEN r.source_conversation_id = $conversation_id THEN null
                        ELSE r.source_conversation_id
                    END,
                    r.source_message_id = CASE
                        WHEN r.source_message_id IN $source_message_ids THEN null
                        ELSE r.source_message_id
                    END,
                    r.last_source_conversation_id = CASE
                        WHEN r.last_source_conversation_id = $conversation_id THEN null
                        ELSE r.last_source_conversation_id
                    END,
                    r.last_source_message_id = CASE
                        WHEN r.last_source_message_id IN $source_message_ids THEN null
                        ELSE r.last_source_message_id
                    END,
                    r.source_deleted = true,
                    r.updated_at = timestamp()
                RETURN count(r) AS count
                """,
                conversation_id=conversation_id,
                source_message_ids=source_message_ids,
            ).single()
            stats["relationships_unlinked"] = relationship_cleanup["count"] if relationship_cleanup else 0

            delete_facts = session.run(
                """
                MATCH ()-[r]->()
                WHERE coalesce(r.source_deleted, false) = true
                  AND r.source_conversation_id IS NULL
                  AND size(coalesce(r.source_conversation_ids, [])) = 0
                DELETE r
                RETURN count(r) AS count
                """
            ).single()
            stats["facts_deleted"] = delete_facts["count"] if delete_facts else 0

            node_cleanup = session.run(
                """
                MATCH (n:Entity)
                WHERE n.source_conversation_id = $conversation_id
                   OR n.last_source_conversation_id = $conversation_id
                   OR $conversation_id IN coalesce(n.source_conversation_ids, [])
                WITH n,
                     [item IN coalesce(n.source_conversation_ids, [])
                      WHERE item <> $conversation_id] AS remaining_conversation_ids,
                     [item IN coalesce(n.source_message_ids, [])
                      WHERE NOT (item IN $source_message_ids)] AS remaining_message_ids
                SET n.source_conversation_ids = remaining_conversation_ids,
                    n.source_message_ids = remaining_message_ids,
                    n.source_conversation_id = CASE
                        WHEN n.source_conversation_id = $conversation_id THEN null
                        ELSE n.source_conversation_id
                    END,
                    n.source_message_id = CASE
                        WHEN n.source_message_id IN $source_message_ids THEN null
                        ELSE n.source_message_id
                    END,
                    n.last_source_conversation_id = CASE
                        WHEN n.last_source_conversation_id = $conversation_id THEN null
                        ELSE n.last_source_conversation_id
                    END,
                    n.last_source_message_id = CASE
                        WHEN n.last_source_message_id IN $source_message_ids THEN null
                        ELSE n.last_source_message_id
                    END,
                    n.source_deleted = true,
                    n.updated_at = timestamp()
                RETURN count(n) AS count
                """,
                conversation_id=conversation_id,
                source_message_ids=source_message_ids,
            ).single()
            stats["nodes_unlinked"] = node_cleanup["count"] if node_cleanup else 0

            delete_orphans = session.run(
                """
                MATCH (n:Entity)
                WHERE coalesce(n.source_deleted, false) = true
                  AND n.source_conversation_id IS NULL
                  AND size(coalesce(n.source_conversation_ids, [])) = 0
                  AND NOT EXISTS { MATCH (n)-[r]-() WHERE type(r) <> 'RESOLVES_TO' }
                DETACH DELETE n
                RETURN count(n) AS count
                """
            ).single()
            stats["orphan_nodes_deleted"] = delete_orphans["count"] if delete_orphans else 0
            session.run(
                "MATCH (identity:EntityIdentity) "
                "WHERE NOT (identity)-[:RESOLVES_TO]->() DETACH DELETE identity"
            )

        logger.info("Removed graph provenance for conversation %s: %s", conversation_id, stats)
        return stats
