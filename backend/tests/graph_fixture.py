"""Deterministic driver fixture for verifying ordered Cypher and provenance params."""
from collections import defaultdict
from datetime import datetime, timezone


class FixtureResult:
    def __init__(self, row, rows=None):
        self.row = row
        self.rows = [row] if rows is None else rows

    def single(self):
        return self.row

    def __iter__(self):
        return iter(self.rows)


class FixtureDriver:
    def __init__(self, ambiguous=False, fail=False):
        self.calls = []
        self.transactions = 0
        self.ambiguous = ambiguous
        self.fail = fail

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute_write(self, callback):
        self.transactions += 1
        return callback(self)

    def run(self, query, **parameters):
        self.calls.append({"query": " ".join(query.split()), "parameters": parameters})
        if self.fail:
            raise RuntimeError("fixture storage failure")
        row = defaultdict(lambda: None, {
            "name": "nafiz", "labels": ["Entity", "Person"], "identity_context": "",
            "importance": 1.0, "entity_key": "person:nafiz", "count": 1,
            "linked_keys": ["person:a", "person:b"] if self.ambiguous else [],
            "fact_ids": ["fact:old"], "newest_event_at": 0, "fact_id": "fact:new",
            "source_message_ids": ["message:old"], "is_current": True,
            "source_id": 1, "target_id": 2, "source_key": "person:nafiz", "target_key": "location:surabaya",
            "source_name": "nafiz", "target_name": "surabaya", "source_labels": ["Entity", "Person"],
            "target_labels": ["Entity", "Location"], "source_importance": 1.0, "target_importance": 1.0,
            "rel_type": "LIVES_IN", "n_labels": ["Entity", "Person"], "m_labels": ["Entity", "Location"],
            "n.name": "nafiz", "m.name": "surabaya", "type(r)": "LIVES_IN", "last_confirmed_at": 1000,
            "deleted": {"entity_key": "person:nafiz", "name": "nafiz"},
        })
        return FixtureResult(row, [] if "ORDER BY person.entity_key" in query else None)


EVENT = datetime(2026, 9, 13, tzinfo=timezone.utc)
NODES = [{"id": "nafiz", "label": "Person", "name": "Nafiz"},
         {"id": "surabaya", "label": "Location", "name": "Surabaya"}]


def execute_scenario(store_type, name):
    driver = FixtureDriver(ambiguous=name == "ambiguous_identity", fail=name == "write_failure")
    store = store_type.__new__(store_type)
    store.driver = driver
    if name in {"scoped_merge", "explicit_retraction", "write_failure"}:
        result = store.merge_knowledge(
            NODES,
            [{"source": "nafiz", "target": "surabaya", "relation": "BORN_IN", "supersedes": ["fact:old"]}],
            retractions=[{"source": "nafiz", "target": "surabaya", "relation": "LIVES_IN"}] if name == "explicit_retraction" else [],
            source_conversation_id="conversation:fixture", source_message_id="message:fixture",
            project_id="project:fixture", project_name="Claire", event_id="event:fixture", event_at=EVENT,
        )
    elif name == "ambiguous_identity":
        result = store.merge_knowledge(
            [{"id": "adel", "label": "Person", "name": "Adel", "identity_context": "teman Nafiz"}], [],
            source_message_id="message:fixture", event_id="event:fixture", event_at=EVENT,
        )
    elif name == "graph_read":
        result = store.get_graph_data(limit=12, include_inactive=True)
    elif name == "search":
        result = store.search_knowledge(["Nafiz", "Surabaya"], project_id="project:fixture", include_historical=True)
    elif name == "node_update":
        result = store.update_node("person:nafiz", {"importance": 2.0})
    elif name == "fact_update":
        result = store.update_fact("fact:fixture", {"is_current": False, "importance": 0.5})
    elif name == "node_delete":
        result = store.delete_node("person:nafiz")
    elif name == "fact_delete":
        result = store.delete_fact("fact:fixture")
    elif name == "provenance_cleanup":
        result = store.remove_conversation_provenance("conversation:fixture", ["message:fixture"])
    elif name == "consolidation":
        result = store.consolidate_memory(days_passed=2)
    else:
        raise ValueError(name)
    return {"calls": driver.calls, "transactions": driver.transactions, "result": result}


SCENARIOS = ["scoped_merge", "explicit_retraction", "ambiguous_identity", "graph_read", "search",
             "node_update", "fact_update", "node_delete", "fact_delete", "provenance_cleanup", "consolidation"]
