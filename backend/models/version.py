from sqlalchemy import Column, String, Integer, Text, JSON
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class RecordVersion(Base, TimestampedUUIDMixin):
    """
    record_versions(entity_type, entity_id, version, snapshot JSON, change_reason, actor_id)
    Rule 8: Records are versioned, never silently overwritten.
    """
    __tablename__ = "record_versions"

    entity_type = Column(String(64), nullable=False, index=True)  # ENROLLMENT, PROGRAM_APPROVAL, STUDENT
    entity_id = Column(String(36), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    change_reason = Column(Text, nullable=False)
    actor_id = Column(String(64), nullable=False)
