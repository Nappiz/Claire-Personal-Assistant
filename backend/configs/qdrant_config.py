from qdrant_client import QdrantClient
from configs.settings import settings
import logging
import os

logger = logging.getLogger(__name__)

# Memastikan direktori untuk Qdrant ada
os.makedirs(settings.QDRANT_PATH, exist_ok=True)

try:
    # Menginisialisasi Qdrant dalam local embedded mode
    qdrant_db = QdrantClient(path=settings.QDRANT_PATH)
    logger.info(f"Qdrant initialized at {settings.QDRANT_PATH}")
except Exception as e:
    logger.error(f"Failed to initialize Qdrant: {e}")
    qdrant_db = None
