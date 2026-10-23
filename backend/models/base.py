import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from backend.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class TimestampedUUIDMixin:
    """Provides UUID primary key and created_at / updated_at timestamps for all 15 models."""
    id = Column(String(36), primary_key=True, default=generate_uuid, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
