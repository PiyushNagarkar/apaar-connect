from sqlalchemy import Column, String, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class IdentityCheck(Base, TimestampedUUIDMixin):
    """
    identity_checks(student_id, request_id, source, status, exists, name_match, dob_match, raw JSON)
    Rule 1: source is MOCK_APAAR_V1
    """
    __tablename__ = "identity_checks"

    student_id = Column(String(36), ForeignKey("students.id"), nullable=True, index=True)
    request_id = Column(String(64), nullable=False, index=True)
    source = Column(String(64), default="MOCK_APAAR_V1", nullable=False)  # Rule 1
    status = Column(String(32), nullable=False)  # PASSED, FAILED, PENDING, UNAVAILABLE, NOT_PROVIDED
    exists = Column(Boolean, nullable=True)
    name_match = Column(Boolean, nullable=True)
    dob_match = Column(Boolean, nullable=True)
    raw = Column(JSON, nullable=True)

    student = relationship("Student", back_populates="identity_checks")
