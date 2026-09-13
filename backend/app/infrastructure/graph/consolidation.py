import logging
import math

logger = logging.getLogger(__name__)

class GraphConsolidation:
    def consolidate_memory(self, days_passed: float = 1.0) -> dict:
        """
        Background Job: Perawatan memori agar Neo4j tidak membengkak (Hairball Prevention).
        1. Decay: Mengurangi importance berdasarkan akumulasi hari lewat (0.9 ^ days_passed)
        2. Prune Orphans: Menghapus node yatim tanpa relasi.
        3. Forget: Menghapus node lama berimportance rendah *hanya* jika node
           tidak mendukung fact yang masih current.
        """
        requested_days = float(days_passed)
        if not math.isfinite(requested_days):
            raise ValueError("days_passed must be a finite number")
        safe_days_passed = min(max(requested_days, 0.0), 30.0)
        if safe_days_passed != requested_days:
            logger.warning("Clamped memory consolidation days from %s to %s", requested_days, safe_days_passed)
        stats = {
            "expired_states": 0,
            "decayed": 0,
            "pruned_orphans": 0,
            "forgotten_nodes": 0,
            "protected_current_nodes": 0,
        }
        decay_factor = 0.9 ** safe_days_passed

        try:
            with self.driver.session() as session:
                expiration_result = session.run("""
                    MATCH ()-[r]->()
                    WHERE coalesce(r.is_current, true) = true
                      AND r.expires_at IS NOT NULL
                      AND r.expires_at <= timestamp()
                    SET r.is_current = false,
                        r.expired_at = timestamp(),
                        r.updated_at = timestamp()
                    RETURN count(r) AS count
                """)
                stats["expired_states"] = expiration_result.single()["count"]

                # 1. Decay importance
                query = "MATCH (n:Entity) WHERE n.importance IS NOT NULL SET n.importance = n.importance * $decay RETURN count(n) AS count"
                result = session.run(query, decay=decay_factor)
                stats["decayed"] = result.single()["count"]

                protected_query = """
                MATCH (n:Entity)
                WHERE EXISTS {
                    MATCH (n)-[r]-()
                    WHERE type(r) <> 'RESOLVES_TO' AND coalesce(r.is_current, true) = true
                }
                RETURN count(n) AS count
                """
                result = session.run(protected_query)
                stats["protected_current_nodes"] = result.single()["count"]

                # 2. Delete forgotten nodes only when they are unrelated to every
                # active fact. A valid but seldom-mentioned family/job/etc. must
                # not disappear merely because its ranking score decayed.
                # 30 days in ms = 30 * 24 * 60 * 60 * 1000 = 2592000000
                forget_query = """
                MATCH (n:Entity)\x20
                WHERE n.importance < 0.2\x20
                AND n.updated_at < (timestamp() - 2592000000)
                AND NOT EXISTS {
                    MATCH (n)-[r]-()
                    WHERE type(r) <> 'RESOLVES_TO' AND coalesce(r.is_current, true) = true
                }
                DETACH DELETE n RETURN count(n) AS count
                """
                result = session.run(forget_query)
                stats["forgotten_nodes"] = result.single()["count"]

                # 3. Prune orphan nodes (no connections at all)
                prune_query = """
                MATCH (n:Entity)\x20
                WHERE NOT EXISTS { MATCH (n)-[r]-() WHERE type(r) <> 'RESOLVES_TO' }
                DETACH DELETE n RETURN count(n) AS count
                """
                result = session.run(prune_query)
                stats["pruned_orphans"] = result.single()["count"]
                session.run(
                    "MATCH (identity:EntityIdentity) "
                    "WHERE NOT (identity)-[:RESOLVES_TO]->() DETACH DELETE identity"
                )

                logger.info(f"Memory Consolidation Done: {stats}")
                return stats
        except Exception as e:
            logger.error(f"Error in consolidate_memory: {e}")
            return stats
