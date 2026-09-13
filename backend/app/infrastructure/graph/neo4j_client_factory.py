from neo4j import GraphDatabase
import logging
from configs.settings import settings
from app.domain.graph.fact_policy import RELATION_POLICIES

logger = logging.getLogger(__name__)

class Neo4jConnection:
    def __init__(self):
        self.available = False
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        try:
            self.driver.verify_connectivity()
            self.available = True
            logger.info("Connected to Neo4j successfully!")
            
            # ``name`` is only a display value. It cannot be unique: two people
            # can legitimately share a name. Migrate old installations before
            # enforcing the contextual identity key used by new graph writes.
            with self.driver.session() as session:
                session.run("DROP CONSTRAINT unique_entity_name IF EXISTS")
                session.run("""
                    MATCH (e:Entity)
                    WHERE e.entity_key IS NULL
                    SET e.entity_key = 'legacy:' + elementId(e),
                        e.display_name = coalesce(e.display_name, e.name)
                """)
                session.run("CREATE CONSTRAINT unique_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_key IS UNIQUE")
                session.run("CREATE CONSTRAINT unique_residence_retraction IF NOT EXISTS FOR (r:ResidenceRetraction) REQUIRE r.marker_key IS UNIQUE")
                session.run(
                    "CREATE CONSTRAINT unique_person_identity_registry IF NOT EXISTS "
                    "FOR (i:EntityIdentity) REQUIRE i.identity_key IS UNIQUE"
                )
                session.run("CREATE INDEX entity_name_lookup IF NOT EXISTS FOR (e:Entity) ON (e.name)")
                session.run(
                    "CREATE FULLTEXT INDEX entity_identity_search IF NOT EXISTS "
                    "FOR (e:Entity) ON EACH [e.name, e.identity_context]"
                )
                session.run("CALL db.awaitIndex('entity_identity_search', 30)")
                # Backfill temporal/provenance identifiers for relationships
                # created by older versions. randomUUID() is evaluated once
                # per relationship, so every fact remains individually editable.
                session.run("""
                    MATCH ()-[r]->()
                    SET r.fact_id = coalesce(r.fact_id, randomUUID()),
                        r.created_at = coalesce(r.created_at, r.updated_at, timestamp()),
                        r.last_confirmed_at = coalesce(r.last_confirmed_at, r.updated_at, r.created_at, timestamp()),
                        r.is_current = coalesce(r.is_current, true),
                        r.importance = coalesce(r.importance, 1.0),
                        r.memory_kind = coalesce(r.memory_kind, 'fact'),
                        r.review_status = coalesce(r.review_status, 'approved'),
                        r.scope = coalesce(r.scope, CASE WHEN r.project_id IS NULL THEN 'global' ELSE 'project' END),
                        r.scope_key = coalesce(r.scope_key, r.project_id, 'global'),
                        r.observed_at = coalesce(r.observed_at, r.created_at, timestamp()),
                        r.valid_from = coalesce(r.valid_from, r.created_at, timestamp())
                """)
                for relation, policy in RELATION_POLICIES.items():
                    session.run(
                        f"""
                        MATCH ()-[r:{relation}]->()
                        SET r.memory_kind = $memory_kind,
                            r.expires_at = CASE
                                WHEN $ttl_ms IS NULL THEN r.expires_at
                                ELSE coalesce(r.expires_at, coalesce(r.observed_at, r.created_at, timestamp()) + $ttl_ms)
                            END
                        """,
                        memory_kind=policy.kind,
                        ttl_ms=policy.ttl_milliseconds,
                    )
                session.run("""
                    MATCH ()-[r]->()
                    WHERE coalesce(r.is_current, true) = true
                      AND r.expires_at IS NOT NULL
                      AND r.expires_at <= timestamp()
                    SET r.is_current = false,
                        r.expired_at = timestamp(),
                        r.updated_at = timestamp()
                """)
                
        except Exception as e:
            self.available = False
            logger.error(f"Failed to connect to Neo4j: {e}")

    def close(self):
        self.driver.close()
