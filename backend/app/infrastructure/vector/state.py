from configs.settings import settings
import threading

COLLECTION_NAME = settings.QDRANT_MEMORY_COLLECTION
LEGACY_COLLECTION_NAME = "personia_memory"
encoder = None
VECTOR_SIZE = 0
_encoder_error: str | None = None
_encoder_load_attempted = False
_encoder_failure_count = 0
_encoder_next_retry_at = 0.0
_pending_encoder = None
_encoder_lock = threading.Lock()
client = None
_client_error: str | None = None
_client_lock = threading.Lock()
