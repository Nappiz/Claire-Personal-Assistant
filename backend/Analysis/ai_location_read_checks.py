"""Read-only inspection of the reported spatial graph and source messages."""
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url
from neo4j import GraphDatabase
from configs.settings import settings


def main():
    url = make_url(settings.DATABASE_URL)
    if url.drivername.startswith("sqlite") and url.database:
        with sqlite3.connect("file:" + url.database.replace("\\", "/") + "?mode=ro", uri=True) as db:
            rows = db.execute("""SELECT id, conversation_id, content, created_at FROM messages
                WHERE role='user' AND (lower(content) LIKE '%adel%' OR lower(content) LIKE '%agung sedayu%'
                    OR lower(content) LIKE '%kuliah di its%' OR lower(content) LIKE '%tinggal di pik%')
                ORDER BY created_at DESC LIMIT 25""").fetchall()
            print(json.dumps({"sources": [dict(zip(("id", "session", "content", "created_at"), row)) for row in rows]}, ensure_ascii=False))
            jobs = db.execute("""SELECT id, user_message_id, extracted_knowledge, status
                FROM memory_outbox WHERE user_message_id IN
                ('dc90fbe0-a9b5-4195-8054-e071d04c4cd8', '16fb916e-b596-4d32-8be9-98ff95e06785', 'e9b6869a-95b0-4ada-a8ea-d34c66341c94')""").fetchall()
            print(json.dumps({"jobs": [{"id": row[0], "message": row[1], "extraction": json.loads(row[2] or "{}"), "status": row[3]} for row in jobs]}, ensure_ascii=False))
    with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                              connection_timeout=3) as driver:
        with driver.session() as session:
            rows = session.run("""MATCH (p:Entity:Person)-[r]->(b:Entity)
                WHERE p.name IN ['nafiz', 'adel'] AND type(r) IN ['LIVES_IN', 'STUDIED_AT', 'WORKS_AT', 'INTERNS_AT']
                RETURN p.entity_key AS source_key, p.name AS person, p.identity_context AS identity,
                       type(r) AS relation, b.name AS target, b.entity_key AS target_key,
                       r.fact_id AS fact_id, r.is_current AS current, r.review_status AS review,
                       r.source_event_at AS source_event_at, r.lifecycle_event_at AS lifecycle_event_at,
                       coalesce(r.source_message_ids, []) AS source_message_ids,
                       r.source_message_id AS source_message_id ORDER BY r.updated_at DESC LIMIT 40""", timeout=5)
            print(json.dumps({"graph": [dict(row) for row in rows]}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
