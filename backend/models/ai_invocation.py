"""One durable record per provider request attempt, independent of chat commits."""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON
from .base import Base


class AIInvocation(Base):
    __tablename__ = "ai_invocations"
    id = Column(String(36), primary_key=True)
    purpose = Column(String(40), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    conversation_id = Column(String(36), nullable=True, index=True)
    turn_id = Column(String(36), nullable=True, index=True)
    job_id = Column(String(36), nullable=True, index=True)
    attempt = Column(Integer, nullable=False)
    job_attempt = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    latency_ms = Column(Float, nullable=True)
    provider_request_id = Column(String(255), nullable=True)
    response_id = Column(String(255), nullable=True)
    finish_reason = Column(String(50), nullable=True)
    error_type = Column(String(100), nullable=True)
    usage_available = Column(Boolean, nullable=False, default=False)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    usage_details = Column(JSON, nullable=True)
    total_cost = Column(Float, nullable=True)
