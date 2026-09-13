import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from .base import Base


def get_uuid():
    return str(uuid.uuid4())


class MemoryOutbox(Base):
    """Durable work record for eventually saving one chat turn to memory stores."""

    __tablename__ = "memory_outbox"

    id = Column(String(36), primary_key=True, default=get_uuid)
    conversation_id = Column(String(36), nullable=False, index=True)
    user_message_id = Column(String(36), nullable=True, index=True)
    user_message = Column(Text, nullable=False)
    assistant_response = Column(Text, nullable=False)
    session_history = Column(JSON, nullable=False, default=list)
    neo4j_context = Column(JSON, nullable=False, default=list)
    extracted_knowledge = Column(JSON, nullable=True)
    project_id = Column(String(36), nullable=True, index=True)
    project_name = Column(String(120), nullable=True)
    scope = Column(String(20), nullable=False, default="global", index=True)

    vector_saved = Column(Boolean, nullable=False, default=False)
    extraction_completed = Column(Boolean, nullable=False, default=False)
    graph_saved = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    lease_token = Column(String(36), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    event_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
