import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from .base import Base

def get_uuid():
    return str(uuid.uuid4())

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(String(36), primary_key=True, default=get_uuid)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    recurrence = Column(String(50), nullable=True)
    status = Column(String(20), default='pending')
    priority = Column(String(20), default='medium')
    source_conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
