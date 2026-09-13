import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

def get_uuid():
    return str(uuid.uuid4())

class LLMUsageLog(Base):
    __tablename__ = "llm_usage_log"

    id = Column(String(36), primary_key=True, default=get_uuid)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_cost = Column(Float, nullable=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    conversation = relationship("Conversation", back_populates="llm_usages")
