"""VectorStore port exercised against a real in-memory Qdrant fixture."""
from unittest import TestCase
from unittest.mock import patch
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from app.infrastructure.vector import state, chunker, embedding_encoder
from app.infrastructure.vector.qdrant_vector_store import QdrantVectorStore
from app.ports.vector_store import VectorStore


class VectorAdapterTests(TestCase):
    def test_port_projection_reconcile_lifecycle_and_session_delete(self):
        client = QdrantClient(":memory:")
        client.create_collection(state.COLLECTION_NAME, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
        adapter = QdrantVectorStore()
        event_id = str(uuid.UUID("1dd6c58c-b970-4d40-a5e1-8cde0848a845"))
        text = "Saya bekerja di Proyek Claire"
        metadata = {"source_role": "user", "epistemic_status": "user_assertion", "session_id": "session-fixture",
                    "message_id": "message-fixture", "project_id": "project-fixture",
                    "assertion_spans": [{"text": text, "modality": "asserted_fact", "polarity": "positive"}],
                    "stored_at": "2026-09-13T00:00:00+00:00"}
        try:
            with patch.object(state, "client", client), patch.object(chunker, "_memory_chunk_offsets", return_value=[(0, len(text))]), patch.object(
                embedding_encoder, "embed_text", return_value=[1.0, 0.0]
            ) as embed:
                self.assertIsInstance(adapter, VectorStore)
                self.assertEqual(event_id, adapter.save_memory(text, metadata, point_id=event_id))
                point = client.retrieve(state.COLLECTION_NAME, [event_id], with_payload=True)[0]
                self.assertEqual("project", point.payload["scope"])
                self.assertEqual(2, point.payload["evidence_version"])
                self.assertEqual(0, point.payload["chunk_index"])
                self.assertEqual(embedding_encoder.embedding_signature(), point.payload["embedding_signature"])
                embed.reset_mock()
                self.assertFalse(adapter.reconcile_memory(text, metadata, point_id=event_id))
                embed.assert_not_called()
                results = adapter.search_memory("Proyek Claire", project_id="project-fixture")
                self.assertEqual(["message-fixture"], [result["message_id"] for result in results])
                adapter.set_memories_status(["message-fixture"], status="inactive")
                self.assertEqual([], adapter.search_memory("Proyek Claire", project_id="project-fixture"))
                adapter.delete_memory_by_session("session-fixture")
                self.assertEqual(0, client.count(state.COLLECTION_NAME).count)
        finally:
            client.close()
