import uuid
from datetime import datetime, timezone
from sqlalchemy import JSON, Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, case
from sqlalchemy.orm import relationship
from .base import Base

def get_uuid():
    return str(uuid.uuid4())

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_id", "role", name="uq_message_turn_role"),
    )

    id = Column(String(36), primary_key=True, default=get_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(30), nullable=False, default="normal", server_default="normal")
    error_details = Column(JSON, nullable=True)
    token_count = Column(Integer, nullable=True)
    memory_status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    turn_id = Column(String(36), nullable=True, index=True)
    turn_sequence = Column(Integer, nullable=True, index=True)
    response_status = Column(String(20), nullable=False, default="complete", server_default="complete")
    finish_reason = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def chronological_order(*, descending: bool = False):
        """Order by durable turn and role before provider/wall-clock timestamps."""
        fields = (
            Message.turn_sequence,
            case((Message.role == "user", 0), else_=1),
            Message.created_at,
            Message.id,
        )
        return tuple(field.desc() if descending else field.asc() for field in fields)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
