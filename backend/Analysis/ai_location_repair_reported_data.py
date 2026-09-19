"""Scoped, idempotent repair of the three inspected source messages.

Default: a dry plan. --apply backs up changed records, coordinates graph/vector
invalidation through the running API, fixes cached extraction, and restores
only grounded institution/office relations. No model API is called.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url
from neo4j import GraphDatabase
from configs.settings import settings
from services.location_grounding import ground_locations
from services.memory_policy import validate_extracted_knowledge
from services.neo4j_service import Neo4jService

SOURCES = {
    "dc90fbe0-a9b5-4195-8054-e071d04c4cd8": "Magang di Agung Sedayu Group",
    "16fb916e-b596-4d32-8be9-98ff95e06785": "ya adel temenku",
    "e9b6869a-95b0-4ada-a8ea-d34c66341c94": "temenku namanya adel dia kuliah di UB",
}
API = "http://127.0.0.1:8100/api/v1"


def triples(data):
    nodes = {node["id"]: node for node in data["nodes"]}
    keys = {id: Neo4jService._entity_key(node["label"], node["name"], node.get("identity_context", "")) for id, node in nodes.items()}
    return {(keys[edge["source"]], edge["relation"], keys[edge["target"]]) for edge in data["edges"]}


def main(apply=False):
    url = make_url(settings.DATABASE_URL)
    assert url.drivername.startswith("sqlite") and url.database, "This repair requires the inspected local SQLite database"
    database = Path(url.database).resolve()
    assert database.is_file()
    changes = []
    with sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        for source_id, expected in SOURCES.items():
            rows = db.execute("""SELECT j.id, j.conversation_id, j.user_message_id, j.user_message,
                j.session_history, j.neo4j_context, j.extracted_knowledge, j.status, j.event_at,
                m.memory_status, c.deleted_at FROM memory_outbox j
                JOIN messages m ON m.id=j.user_message_id JOIN conversations c ON c.id=j.conversation_id
                WHERE j.user_message_id=?""", (source_id,)).fetchall()
            assert len(rows) == 1, f"Expected one inspected job for {source_id}"
            row = dict(rows[0])
            assert expected.casefold() in row["user_message"].casefold(), "Source content changed"
            assert row["status"] == "completed" and row["deleted_at"] is None, "Source job is active or deleted"
            original = json.loads(row["extracted_knowledge"])
            grounded = validate_extracted_knowledge(ground_locations(original, row["user_message"],
                json.loads(row["session_history"] or "[]"), json.loads(row["neo4j_context"] or "[]")))
            if grounded != original:
                changes.append({"row": row, "original": original, "grounded": grounded,
                                "removed": triples(original) - triples(grounded), "added": triples(grounded) - triples(original)})
    removed = set().union(*(change["removed"] for change in changes)) if changes else set()
    added = set().union(*(change["added"] for change in changes)) if changes else set()
    with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
        with driver.session() as session:
            graph = [dict(row) for row in session.run("""MATCH (a:Entity)-[r]->(b:Entity)
                WHERE r.source_message_id IN $ids OR any(id IN coalesce(r.source_message_ids, []) WHERE id IN $ids)
                RETURN a.entity_key AS source, type(r) AS relation, b.entity_key AS target,
                       r.fact_id AS fact_id, coalesce(r.is_current, true) AS current, properties(r) AS properties""", ids=list(SOURCES))]
        affected = [row for row in graph if (row["source"], row["relation"], row["target"]) in removed]
        for row in affected:
            provenance = set(row["properties"].get("source_message_ids", []))
            if row["properties"].get("source_message_id"):
                provenance.add(row["properties"]["source_message_id"])
            assert provenance <= set(SOURCES), "An affected fact has unreviewed additional evidence"
            assert row["fact_id"], "Cannot safely invalidate a fact without durable ID"
        plan = {"changed_jobs": len(changes), "removed_cached_edges": len(removed), "added_grounded_edges": len(added),
                "active_facts_to_invalidate": [row["fact_id"] for row in affected if row["current"]],
                "already_inactive_facts": [row["fact_id"] for row in affected if not row["current"]]}
        print(json.dumps({"plan": plan}, ensure_ascii=False))
        if not apply or not changes:
            return
        with urlopen(API + "/memory/jobs?limit=1", timeout=5) as response:
            assert response.status == 200
        backup_dir = Path(__file__).resolve().parents[1] / "data" / "repairs"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / ("location_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        backup_path.write_text(json.dumps({"plan": plan, "graph": affected,
            "jobs": [{"id": change["row"]["id"], "user_message_id": change["row"]["user_message_id"],
                      "memory_status": change["row"]["memory_status"], "extracted_knowledge": change["original"]}
                     for change in changes]}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        for row in affected:
            if not row["current"]:
                continue
            request = Request(API + "/memory/graph/fact/" + row["fact_id"], method="PATCH",
                              data=b'{"is_current":false}', headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=15) as response:
                assert response.status == 200
                json.load(response)
        with sqlite3.connect(str(database), timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            for change in changes:
                row = change["row"]
                result = db.execute("""UPDATE memory_outbox SET extracted_knowledge=?, updated_at=?
                    WHERE id=? AND status='completed' AND extracted_knowledge=?""",
                    (json.dumps(change["grounded"], ensure_ascii=False), datetime.now(timezone.utc).isoformat(sep=" "),
                     row["id"], row["extracted_knowledge"]))
                assert result.rowcount == 1, "Cached extraction changed concurrently"
        service = object.__new__(Neo4jService)
        service.driver = driver
        for change in changes:
            row, data = change["row"], change["grounded"]
            if data["edges"]:
                service.merge_knowledge(data["nodes"], data["edges"], source_conversation_id=row["conversation_id"],
                    source_message_id=row["user_message_id"], event_id=row["id"], event_at=datetime.fromisoformat(row["event_at"]))
        with driver.session() as session:
            active = session.run("""MATCH ()-[r]->() WHERE r.fact_id IN $ids AND coalesce(r.is_current, true)
                RETURN count(r) AS count""", ids=[row["fact_id"] for row in affected]).single()["count"]
            assert active == 0, "An unsupported fact remained active"
            for source, relation, target in added:
                found = session.run("""MATCH (a:Entity {entity_key: $source})-[r]->(b:Entity {entity_key: $target})
                    WHERE type(r)=$relation AND coalesce(r.is_current, true) RETURN count(r) AS count""",
                    source=source, target=target, relation=relation).single()["count"]
                assert found == 1, "A grounded replacement is missing or duplicated"
        print(json.dumps({"applied": True, "invalidated": len(plan["active_facts_to_invalidate"]),
                          "grounded_additions_verified": len(added), "backup": str(backup_path)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    main(parser.parse_args().apply)
