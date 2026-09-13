"""Regression coverage for Medium-severity graph memory fixes."""

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
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        if "RETURN r.fact_id AS fact_id" in query:
            return _Result(single_record={"fact_id": "fact-new"})
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


class MediumMemoryCorrectnessTests(TestCase):
    def test_short_noisy_keywords_are_rejected(self):
        self.assertIsNone(Neo4jService._prepare_search_keyword("a"))
        self.assertIsNone(Neo4jService._prepare_search_keyword("di"))
        self.assertIsNone(Neo4jService._prepare_search_keyword("an"))

        normalized, pattern = Neo4jService._prepare_search_keyword("Budi")
        self.assertEqual("budi", normalized)
        self.assertIn(r"\p{L}", pattern)

    def test_graph_search_is_word_bounded_and_read_only(self):
        session = _Session()
        _service_with(session).search_knowledge(["budi"])

        query, params = session.calls[0]
        self.assertIn("=~ $token_pattern", query)
        self.assertNotIn(" CONTAINS ", query)
        self.assertNotRegex(query, r"\bSET\s+[nm]\.importance")
        self.assertEqual("budi", params["kw"])

    def test_custom_label_casing_is_preserved_and_validated(self):
        self.assertEqual("BackendDeveloper", Neo4jService._clean_label("BackendDeveloper"))
        self.assertEqual("AI_ENGINEER", Neo4jService._clean_label("AI_ENGINEER"))
        self.assertEqual("BackendDeveloper", Neo4jService._clean_label("Backend Developer"))
        self.assertEqual("Entity", Neo4jService._clean_label("123Invalid"))

    def test_provenance_is_written_to_nodes_and_facts(self):
        session = _Session()
        _service_with(session).merge_knowledge(
            [
                {"id": "person", "label": "Person", "name": "nafiz"},
                {"id": "skill", "label": "BackendDeveloper", "name": "fastapi"},
            ],
            [
                {
                    "source": "person",
                    "target": "skill",
                    "relation": "SKILLED_AT",
                    "supersedes": [],
                }
            ],
            source_conversation_id="conversation-123",
            source_message_id="message-456",
        )

        node_query, node_params = next(
            (query, params) for query, params in session.calls if "MERGE (n:Entity" in query
        )
        fact_query, fact_params = next(
            (query, params) for query, params in session.calls if "RETURN r.fact_id AS fact_id" in query
        )
        self.assertIn("n.source_conversation_ids", node_query)
        self.assertIn("r.source_message_ids", fact_query)
        self.assertEqual("conversation-123", node_params["source_conversation_id"])
        self.assertEqual("message-456", fact_params["source_message_id"])
