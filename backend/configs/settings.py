from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "Personia AI"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    USER_TIMEZONE: str = "Asia/Jakarta"

    # Local web retrieval (SearXNG)
    WEB_SEARCH_ENABLED: bool = True
    SEARXNG_URL: str = "http://127.0.0.1:8088"
    WEB_SEARCH_TIMEOUT_SECONDS: float = 3.5
    WEB_SEARCH_MAX_RESULTS: int = 6
    WEB_TOOL_MAX_ROUNDS: int = 3
    WEB_TOOL_PLANNING_TIMEOUT_SECONDS: float = 20.0
    WEB_READ_MAX_URLS: int = 2
    WEB_READ_MAX_CHARS: int = 5000
    WEB_READ_TIMEOUT_SECONDS: float = 15.0
    JINA_READER_URL: str = "https://r.jina.ai"
    JINA_API_KEY: Optional[str] = None
    
    # LLM API Keys
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    LLM_TIMEOUT_SECONDS: float = 90.0
    LLM_MAX_RETRIES: int = 1
    MEMORY_LLM_TIMEOUT_SECONDS: float = 15.0
    MEMORY_LLM_MAX_RETRIES: int = 0
    MEMORY_LLM_PROVIDER: str = "google"
    MEMORY_LLM_MODEL: str = "gemini-3.1-flash-lite"
    MEMORY_LLM_FALLBACK_PROVIDER: Optional[str] = None
    MEMORY_LLM_FALLBACK_MODEL: Optional[str] = None
    MEMORY_FACT_CONFIDENCE_THRESHOLD: float = 0.70
    
    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    
    # SQLite
    DATABASE_URL: str
    
    # Qdrant
    QDRANT_PATH: str
    QDRANT_MEMORY_COLLECTION: str = "personia_memory_e5_v1"
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-large"
    EMBEDDING_MODEL_REVISION: str = ""
    EMBEDDING_INIT_RETRY_BASE_SECONDS: float = 2.0
    EMBEDDING_INIT_RETRY_MAX_SECONDS: float = 60.0
    MEMORY_SEARCH_SCORE_THRESHOLD: float = 0.75
    MEMORY_RETRIEVAL_TIMEOUT_SECONDS: float = 6.0
    MEMORY_RETRIEVAL_WORKERS: int = 8
    CHAT_INPUT_TOKEN_BUDGET: int = 24_000
    CHAT_OUTPUT_MAX_TOKENS: int = 2_048
    TURN_LEASE_SECONDS: int = 300
    
    # HuggingFace (Optional)
    HF_TOKEN: Optional[str] = None
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
