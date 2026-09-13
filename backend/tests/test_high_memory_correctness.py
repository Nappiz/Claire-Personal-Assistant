"""Regression coverage for High-severity graph memory correctness fixes."""

from unittest import TestCase

from services.neo4j_service import Neo4jService


class _Result:
    def __init__(self, records=None, single_record=None):
        self.records = records or []
        self.single_record = single_record

    def __iter__(self):
        return iter(self.records)

    def single(self):
        return self.single_record


class _Session:
    def __init__(self, search_records=None, scripted_singles=None):
        self.calls = []
        self.search_records = search_records or []
        self.scripted_singles = scripted_singles or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        for marker, record in self.scripted_singles.items():
            if marker in query:
                return _Result(single_record=record)
        if "RETURN r.fact_id AS fact_id" in query:
            return _Result(single_record={"fact_id": "new-fact-id"})
        if "coverage_score" in query:
            return _Result(records=self.search_records)
        return _Result()


class _Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _service_with(session):
    service = object.__new__(Neo4jService)
    service.driver = _Driver(session)
    return service


class HighMemoryCorrectnessTests(TestCase):
    def test_search_filters_inactive_and_orders_before_limit(self):
        records = [
            {
                "n.name": "nafiz",
                "type(r)": "WORKS_AT",
                "m.name": "gojek",
                "n_labels": ["Entity", "Person"],
                "m_labels": ["Entity", "Organization"],
                "n_identity_context": None,
                "m_identity_context": None,
                "fact_id": "fact-new",
                "last_confirmed_at": 1_700_000_000_000,
            }
        ]
        session = _Session(search_records=records)

        facts = _service_with(session).search_knowledge(["nafiz"])

        query = session.calls[0][0]
        self.assertIn("coalesce(r.is_current, true) = true", query)
        self.assertLess(query.index("ORDER BY"), query.index("LIMIT 20"))
        self.assertIn("importance_score DESC, recency_score DESC", query)
        self.assertIn("fact_id: fact-new", facts[0])

    def test_new_fact_has_temporal_fields_and_retires_explicit_old_fact(self):
        session = _Session()
        service = _service_with(session)
        nodes = [
            {"id": "person", "label": "Person", "name": "nafiz"},
            {"id": "company", "label": "Location", "name": "malang"},
        ]
        edges = [
            {
                "source": "person",
                "target": "company",
                "relation": "BORN_IN",
                "supersedes": ["old-fact-id"],
                "replaces_current_relation": True,
            }
        ]

        service.merge_knowledge(nodes, edges)

        fact_query = next(query for query, _ in session.calls if "RETURN r.fact_id AS fact_id" in query)
        retire_query, retire_params = next(
            (query, params) for query, params in session.calls if "old.fact_id IN $old_fact_ids" in query
        )
        self.assertIn("r.created_at = timestamp()", fact_query)
        self.assertIn("r.last_confirmed_at = CASE", fact_query)
        self.assertIn("r.is_current = CASE", fact_query)
        self.assertIn("old.is_current = false", retire_query)
        self.assertEqual(["old-fact-id"], retire_params["old_fact_ids"])
        self.assertEqual("new-fact-id", retire_params["new_fact_id"])
        relation_retire_query = next(
            query for query, _ in session.calls
            if "[old:BORN_IN]" in query and "old.fact_id <> $new_fact_id" in query
        )
        self.assertIn("old.fact_id <> $new_fact_id", relation_retire_query)

    def test_same_source_guard_bounds_supersession(self):
        session = _Session()
        service = _service_with(session)
        service.merge_knowledge(
            [
                {"id": "person", "label": "Person", "name": "nafiz"},
                {"id": "place", "label": "Location", "name": "jakarta"},
            ],
            [
                {
                    "source": "person",
                    "target": "place",
                    "relation": "LIVES_IN",
                    "supersedes": ["old-location"],
                }
            ],
        )

        retire_query = next(query for query, _ in session.calls if "old.fact_id IN $old_fact_ids" in query)
        self.assertIn("MATCH (a:Entity {entity_key: $source})-[old:LIVES_IN]->()", retire_query)

    def test_granular_correction_targets_stable_node_and_fact_ids(self):
        node_session = _Session(
            scripted_singles={
                "DETACH DELETE n": {
                    "deleted": {
                        "entity_key": "person:abc",
                        "name": "wrong person",
                        "identity_context": "old context",
                    }
                }
            }
        )
        deleted = _service_with(node_session).delete_node("person:abc")
        self.assertEqual("person:abc", deleted["entity_key"])
        self.assertEqual("person:abc", node_session.calls[0][1]["entity_key"])

        fact_session = _Session(
            scripted_singles={
                "SET r.is_current": {
                    "fact_id": "fact-123",
                    "source": "nafiz",
                    "target": "old company",
                    "relation": "WORKS_AT",
                    "is_current": False,
                    "importance": 1.0,
                }
            }
        )
        updated = _service_with(fact_session).update_fact("fact-123", {"is_current": False})
        query, params = fact_session.calls[0]
        self.assertIn("WHERE r.fact_id = $fact_id", query)
        self.assertEqual("fact-123", params["fact_id"])
        self.assertFalse(updated["is_current"])
