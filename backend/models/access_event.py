from sqlalchemy import Column, String, DateTime, JSON
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class AccessEvent(Base, TimestampedUUIDMixin):
    """
    access_events(actor_id, actor_role, record_type, record_id, purpose,
      fields_accessed, ip_address, user_agent, accessed_at)
    Audit requirement: Log every read of a sensitive record (who, what, why/purpose, when).
    Auditor / Admin only access.
    """
    __tablename__ = "access_events"

    actor_id = Column(String(64), nullable=False, index=True)      # Who
    actor_role = Column(String(64), nullable=False, index=True)
    record_type = Column(String(64), nullable=False, index=True)   # What (e.g., STUDENT, ENROLLMENT, IDENTITY_CHECK)
    record_id = Column(String(64), nullable=False, index=True)     # Which record
    purpose = Column(String(128), nullable=False, index=True)      # Why (purpose: ADMISSION_VERIFICATION, AUDIT, etc.)
    fields_accessed = Column(JSON, nullable=True)                  # Which sensitive attributes (apaar_masked, dob, etc.)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    accessed_at = Column(DateTime(timezone=True), nullable=False, index=True)  # When
