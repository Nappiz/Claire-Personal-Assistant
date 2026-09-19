"""Opt-in Neo4j integration checks; synthetic graph writes always roll back.

Run from backend: venv/Scripts/python.exe Analysis/ai_medium_01_10_live_checks.py
Requires the configured local Neo4j server. Does not invoke an LLM or Qdrant.
"""

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import GraphDatabase
from configs.settings import settings
from services.neo4j_service import Neo4jService


class TransactionSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, *args, **kwargs):
        return self.tx.run(*args, **kwargs)

    def execute_write(self, callback):
        return callback(self.tx)


def main():
    driver = GraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    run_id = "mediumcheck" + uuid.uuid4().hex
    results = {}
    try:
        with driver.session() as session:
            # These are the idempotent indexes required by application startup.
            for query in (
                "CREATE CONSTRAINT unique_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_key IS UNIQUE",
                "CREATE CONSTRAINT unique_person_identity_registry IF NOT EXISTS FOR (i:EntityIdentity) REQUIRE i.identity_key IS UNIQUE",
                "CREATE INDEX entity_name_lookup IF NOT EXISTS FOR (e:Entity) ON (e.name)",
                "CREATE FULLTEXT INDEX entity_identity_search IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.identity_context]",
                "CALL db.awaitIndex('entity_identity_search', 30)",
            ):
                session.run(query).consume()
            tx = session.begin_transaction()
            service = object.__new__(Neo4jService)
            service.driver = SimpleNamespace(session=lambda: TransactionSession(tx))
            try:
                def merge(nodes, edges=(), **kwargs):
                    return service.merge_knowledge(
                        nodes, list(edges),
                        source_conversation_id=run_id,
                        source_message_id=str(uuid.uuid4()),
                        **kwargs,
                    )

                atlas, boreal = run_id + "atlas", run_id + "boreal"
                merge(
                    [{"id": "a", "label": "Project", "name": atlas},
                     {"id": "b", "label": "Project", "name": boreal}],
                    [{"source": "a", "target": "b", "relation": "DEPENDS_ON"}],
                    project_id=run_id, project_name=atlas,
                )
                row = tx.run(
                    "MATCH (a:Entity)-[r:DEPENDS_ON]->(b:Entity) "
                    "WHERE r.project_id = $scope RETURN a.entity_key AS a, b.entity_key AS b",
                    scope=run_id,
                ).single()
                assert row and row["a"] != row["b"], "M08 endpoints collapsed"
                assert any(boreal in fact for fact in service.search_knowledge(
                    [atlas, "depends on"], project_id=run_id
                )), "M05/M08 scoped external endpoint became invisible"
                results["M08_distinct_project_endpoints"] = True

                name = run_id + "siska"
                for context in ("ibu nafiz", "ibu dari nafiz", "mother of nafiz"):
                    merge([{"id": "s", "label": "Person", "name": name,
                            "identity_context": context}])
                assert tx.run(
                    "MATCH (p:Entity:Person {name: $name}) RETURN count(p) AS count", name=name
                ).single()["count"] == 1, "M09 paraphrases split Person"
                results["M09_registry_paraphrases"] = True

                legacy_name = run_id + "legacy"
                legacy_key = run_id + ":legacy"
                tx.run(
                    "CREATE (:Entity:Person {entity_key: $key, name: $name, identity_context: 'ibu dari nafiz'})",
                    key=legacy_key, name=legacy_name,
                ).consume()
                merge([{"id": "l", "label": "Person", "name": legacy_name,
                        "identity_context": "ibu nafiz"}])
                assert tx.run(
                    "MATCH (:EntityIdentity)-[:RESOLVES_TO]->(p:Entity {name: $name}) "
                    "RETURN p.entity_key AS key", name=legacy_name,
                ).single()["key"] == legacy_key, "M09 legacy ID was replaced"
                assert service.delete_node(legacy_key), "Registry-aware deletion failed"
                results["M09_legacy_link_and_delete"] = True

                ambiguous_name = run_id + "ambiguous"
                tx.run(
                    "UNWIND [1,2] AS number CREATE (:Entity:Person {entity_key: $prefix + toString(number), "
                    "name: $name, identity_context: 'ibu nafiz'})",
                    prefix=run_id + ":ambiguous:", name=ambiguous_name,
                ).consume()
                outcome = merge([{"id": "u", "label": "Person", "name": ambiguous_name,
                                  "identity_context": "ibu dari nafiz"}])
                assert outcome["invalidated_source_message_ids"], "M09 ambiguous identity accepted"
                results["M09_ambiguity_quarantined"] = True

                person, employer = run_id + "person", run_id + "employer"
                merge(
                    [{"id": "p", "label": "Person", "name": person, "identity_context": run_id},
                     {"id": "e", "label": "Organization", "name": employer}],
                    [{"source": "p", "target": "e", "relation": "WORKS_AT"}],
                )
                tx.run(
                    "MATCH (p:Entity {name: $person}) UNWIND range(1,8) AS number "
                    "CREATE (p)-[:LIKES {importance: 9999, is_current: true}]->"
                    "(:Entity {entity_key: $prefix + toString(number), name: 'noise', importance: 9999})",
                    person=person, prefix=run_id + ":noise:",
                ).consume()
                facts = service.search_knowledge([person, "works at"])
                assert facts and "WORKS_AT" in facts[0] and employer in facts[0], "M05 joint match pruned"
                results["M05_joint_entity_relation_rank"] = True

                service.remove_conversation_provenance(run_id)
                results["M09_registry_provenance_cleanup"] = True
            finally:
                tx.rollback()
        results["synthetic_writes_rolled_back"] = True
        print(json.dumps(results, indent=2))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
