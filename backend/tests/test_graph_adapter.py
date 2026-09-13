import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import uuid

from app.infrastructure.graph.neo4j_graph_store import Neo4jGraphStore
from app.ports.graph_store import GraphStore
from graph_fixture import SCENARIOS, execute_scenario


class GraphAdapterTests(TestCase):
    def test_ordered_operations_match_original_graph_fixture(self):
        expected = json.loads((Path(__file__).parent / "fixtures/graph_operations.json").read_text(encoding="utf-8"))
        self.assertIsInstance(Neo4jGraphStore.__new__(Neo4jGraphStore), GraphStore)
        with patch.object(uuid, "uuid4", return_value=uuid.UUID("04b9c654-1d3f-466f-a51e-32bfbb3c86bb")):
            for name in SCENARIOS:
                with self.subTest(scenario=name):
                    actual = execute_scenario(Neo4jGraphStore, name)
                    self.assertEqual(expected[name], actual)

    def test_write_failure_propagates_from_atomic_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "fixture storage failure"):
            execute_scenario(Neo4jGraphStore, "write_failure")
