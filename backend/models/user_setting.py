from datetime import datetime, timezone
from sqlalchemy import Column, String, JSON, DateTime
from .base import Base

class UserSetting(Base):
    __tablename__ = "user_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
