"""Native Neo4j regression, with isolated UUID entities and exact cleanup."""
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neo4j import GraphDatabase
from configs.settings import settings
from services.neo4j_service import Neo4jService
from services.location_grounding import ground_locations


def main():
    token = uuid.uuid4().hex
    person = {"id": "p", "label": "Person", "name": "audit_person_" + token,
              "identity_context": "isolated location regression " + token, "confidence": 1.0}
    locations = [{"id": key, "label": "Location", "name": "audit_" + key + "_" + token,
                  "identity_context": "", "confidence": 1.0} for key in ("malang", "surabaya", "late", "race")]
    nodes = [person, *locations]
    keys = [Neo4jService._entity_key(node["label"], node["name"], node["identity_context"]) for node in nodes]
    base = datetime.now(timezone.utc) - timedelta(minutes=1)
    def edge(key):
        return {"source": "p", "target": key, "relation": "LIVES_IN", "confidence": 1.0}
    checks = []
    with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
        service = object.__new__(Neo4jService)
        service.driver = driver
        with driver.session() as session:
            assert session.run("MATCH (n:Entity) WHERE n.entity_key IN $keys RETURN count(n) AS count", keys=keys).single()["count"] == 0
        try:
            def state(key):
                with driver.session() as session:
                    return dict(session.run("""MATCH (p:Entity {entity_key: $person})-[r:LIVES_IN]->(b:Entity {entity_key: $target})
                        RETURN r.is_current AS current, r.review_status AS review""", person=keys[0], target=keys[1 + [node["id"] for node in locations].index(key)]).single())
            service.merge_knowledge(nodes, [edge("malang")], source_message_id="fixture-old-" + token, event_id="old-" + token, event_at=base)
            message = f"tapi si {person['name']} itu dia tinggal nya di {locations[1]['name']} sih gak di {locations[0]['name']}"
            correction = ground_locations({"nodes": nodes, "edges": [edge("malang")]}, message)
            result = service.merge_knowledge(**correction, source_message_id="fixture-correction-" + token,
                event_id="correction-" + token, event_at=base + timedelta(seconds=1))
            assert state("malang")["current"] is False
            assert state("surabaya")["current"] is True
            assert "fixture-old-" + token in result["invalidated_source_message_ids"]
            checks.append("targeted correction preserves Surabaya and retires Malang")
            service.merge_knowledge(nodes, [edge("malang")], event_id="stale-replay-" + token, event_at=base)
            assert state("malang")["current"] is False
            checks.append("stale replay cannot reactivate existing retired residence")
            service.merge_knowledge(nodes, [], retractions=[{"source": "p", "target": "late", "relation": "LIVES_IN"}],
                event_id="deny-before-write-" + token, event_at=base + timedelta(seconds=2))
            service.merge_knowledge(nodes, [edge("late")], event_id="late-write-" + token, event_at=base)
            assert state("late") == {"current": False, "review": "pending_stale_event"}
            checks.append("denial before first edge blocks a delayed older write")
            service.merge_knowledge(nodes, [edge("malang")], event_id="new-assertion-" + token, event_at=base + timedelta(seconds=3))
            assert state("malang")["current"] is True
            checks.append("a genuinely newer explicit residence may supersede the denial")
            uncertain_nodes = [{**person, "confidence": 0.1}, *locations]
            service.merge_knowledge(uncertain_nodes, [], retractions=[{"source": "p", "target": "surabaya", "relation": "LIVES_IN", "confidence": 1.0}],
                event_id="uncertain-denial-" + token, event_at=base + timedelta(seconds=5))
            assert state("surabaya")["current"] is True
            checks.append("an uncertain identity cannot retract a supported residence")
            barrier = Barrier(2)
            def write_old():
                barrier.wait(timeout=5)
                service.merge_knowledge(nodes, [edge("race")], event_id="race-old-" + token, event_at=base)
            def deny_new():
                barrier.wait(timeout=5)
                service.merge_knowledge(nodes, [], retractions=[{"source": "p", "target": "race", "relation": "LIVES_IN"}],
                    event_id="race-denial-" + token, event_at=base + timedelta(seconds=4))
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(write_old), executor.submit(deny_new)]
                for future in futures:
                    future.result(timeout=20)
            assert state("race")["current"] is False
            checks.append("concurrent old write and newer denial converge to inactive")
        finally:
            # Every key was checked absent before mutation and contains this
            # fixture's random identity. No user node is matched by name.
            with driver.session() as session:
                session.run("MATCH (m:ResidenceRetraction) WHERE m.source_key = $source DETACH DELETE m", source=keys[0]).consume()
                session.run("MATCH (i:EntityIdentity) WHERE i.identity_key = $source DETACH DELETE i", source=keys[0]).consume()
                session.run("MATCH (n:Entity) WHERE n.entity_key IN $keys DETACH DELETE n", keys=keys).consume()
                assert session.run("MATCH (n:Entity) WHERE n.entity_key IN $keys RETURN count(n) AS count", keys=keys).single()["count"] == 0
    print(json.dumps({"passed": len(checks), "checks": checks, "fixture_cleanup": "verified"}))


if __name__ == "__main__":
    main()
