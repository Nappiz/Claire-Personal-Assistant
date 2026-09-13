from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=24_000, description="Pesan dari user")
    session_id: Optional[str] = Field(None, description="ID sesi untuk tracking history. Kosongkan untuk memulai sesi baru.")
    turn_id: Optional[str] = Field(
        None,
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
    )
    model: Optional[str] = Field(None, description="Model ID spesifik jika ingin menimpa default")
    provider: Optional[str] = Field(None, description="Provider API (google, groq, openai)")
    project_id: Optional[str] = Field(None, description="Scope project untuk sesi baru")

    @field_validator("message")
    @classmethod
    def bound_encoded_message_size(cls, value: str) -> str:
        # Character counts severely understate emoji/CJK token volume. Keep a
        # conservative reserve for system policy, memory, and recent history.
        if len(value.encode("utf-8")) > 32_000:
            raise ValueError("message exceeds the encoded AI input budget")
        return value


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)


class ConversationPinUpdate(BaseModel):
    is_pinned: bool

class RetrievedMemory(BaseModel):
    content: str
    score: float = Field(ge=-1.0, le=1.0)
    source_role: Literal["user"] = "user"
    epistemic_status: Literal["user_assertion"] = "user_assertion"
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    stored_at: Optional[str] = None
    project_id: Optional[str] = None
    scope: Literal["global", "project"] = "global"
    memory_status: Literal["active", "inactive"] = "active"


class RetrievalStatus(BaseModel):
    router: Literal["not_needed", "needed", "router_failed", "forced"] = "not_needed"
    router_available: bool = True
    qdrant_available: bool = True
    neo4j_available: bool = True
    degraded: bool = False
    warnings: List[str] = Field(default_factory=list)


class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    published_at: Optional[str] = None


class WebPageContent(BaseModel):
    title: str = ""
    url: str
    content: str
    fetched_at: Optional[str] = None


class WebSearchContext(BaseModel):
    status: Literal["not_needed", "ok", "no_results", "unavailable", "disabled"] = "not_needed"
    query: Optional[str] = None
    searched_at: Optional[str] = None
    results: List[WebSearchResult] = Field(default_factory=list)
    pages: List[WebPageContent] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ProjectScopeContext(BaseModel):
    status: Literal["none", "resolved", "ambiguous"] = "none"
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    resolution: Optional[Literal["session", "message", "history", "single", "semantic"]] = None
    candidates: List[str] = Field(default_factory=list)


class QueryResolution(BaseModel):
    status: Literal["none", "resolved", "ambiguous"] = "none"
    query: Optional[str] = None
    candidates: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class MemoryContext(BaseModel):
    qdrant_context: List[RetrievedMemory] = Field(default_factory=list)
    neo4j_context: List[str] = Field(default_factory=list)
    retrieval_status: RetrievalStatus = Field(default_factory=RetrievalStatus)
    web_context: WebSearchContext = Field(default_factory=WebSearchContext)
    project_scope: ProjectScopeContext = Field(default_factory=ProjectScopeContext)
    query_resolution: QueryResolution = Field(default_factory=QueryResolution)

class ChatResponse(BaseModel):
    reply: str = Field(..., description="Balasan dari Claire AI")
    session_id: str = Field(..., description="ID sesi obrolan (dikembalikan untuk dipakai di request selanjutnya)")
    turn_id: Optional[str] = Field(None, description="ID durable untuk retry idempotent turn ini")
    response_status: Literal["complete", "incomplete"] = "complete"
    finish_reason: Optional[str] = None
    context_used: MemoryContext = Field(default_factory=MemoryContext, description="Konteks memori yang berhasil ditarik")


class GraphNodeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    identity_context: Optional[str] = Field(None, max_length=500)
    importance: Optional[float] = Field(None, ge=0.0)


class GraphFactUpdate(BaseModel):
    is_current: Optional[bool] = None
    importance: Optional[float] = Field(None, ge=0.0)
