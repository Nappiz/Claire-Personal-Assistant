"""Opt-in M11 check with real cached embedding weights and temporary Qdrant.

Run from backend: venv/Scripts/python.exe Analysis/ai_medium_11_16_embedding_live_checks.py
No provider API, SQLite archive, or user Qdrant collection is accessed.
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client import QdrantClient
from services import qdrant_service


def metadata(text):
    return {
        "session_id": "temporary-integration", "message_id": "temporary-message",
        "source_role": "user", "epistemic_status": "user_assertion",
        "stored_at": "2026-09-13T00:00:00",
        "assertion_spans": [{"text": text, "modality": "asserted_fact", "polarity": "positive"}],
    }


def main():
    client = QdrantClient(location=":memory:")
    try:
        with patch.object(qdrant_service, "client", client):
            active_encoder = qdrant_service._get_encoder()
            a, b, x = [str(uuid.uuid4()) for _ in range(3)]
            fact_a = "Proyek Atlas memakai PostgreSQL untuk database produksi."
            fact_b = "Proyek Boreal memakai Redis untuk cache aplikasi."
            orphan = "Proyek X memakai MySQL untuk database lokal."
            qdrant_service.save_memory(fact_a, metadata(fact_a), point_id=a)
            qdrant_service.save_memory(orphan, metadata(orphan), point_id=x)
            assert client.count(qdrant_service.COLLECTION_NAME).count == 2
            with patch.object(active_encoder, "encode", wraps=active_encoder.encode) as encode:
                assert not qdrant_service.reconcile_memory(fact_a, metadata(fact_a), point_id=a)
                assert qdrant_service.reconcile_memory(fact_b, metadata(fact_b), point_id=b)
                assert not qdrant_service.reconcile_memory(fact_b, metadata(fact_b), point_id=b)
                assert encode.call_count == 1
            assert client.retrieve(qdrant_service.COLLECTION_NAME, [b])
            print(json.dumps({
                "model": qdrant_service.settings.EMBEDDING_MODEL_NAME,
                "dimensions": qdrant_service.VECTOR_SIZE,
                "same_count_missing_event_repaired": True,
                "unchanged_projections_skipped": 2,
                "embedding_calls_during_reconciliation": 1,
                "persistent_user_memory_writes": 0,
            }, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
