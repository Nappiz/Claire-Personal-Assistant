import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

def get_uuid():
    return str(uuid.uuid4())

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=get_uuid)
    title = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, default=0)
    summary = Column(Text, nullable=True)
    summary_version = Column(Integer, nullable=False, default=0)
    summary_through_sequence = Column(Integer, nullable=False, default=0)
    summary_pending = Column(Boolean, nullable=False, default=False)
    next_turn_sequence = Column(Integer, nullable=False, default=1)
    active_turn_id = Column(String(36), nullable=True, index=True)
    active_turn_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    is_archived = Column(Boolean, default=False)
    is_pinned = Column(Boolean, nullable=False, default=False, server_default="0")
    pinned_at = Column(DateTime(timezone=True), nullable=True)
    project_id = Column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    llm_usages = relationship("LLMUsageLog", back_populates="conversation", cascade="all, delete-orphan")
    project = relationship("Project", back_populates="conversations")
