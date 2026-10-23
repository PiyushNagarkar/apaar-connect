from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class CorrectionRequest(Base, TimestampedUUIDMixin):
    """
    correction_requests(enrollment_id, institution_id, requested_by, status,
      reason_code, explanation, proposed_changes, previous_state, approved_by,
      decision_reason, decided_at, version_created)
    Rule 8: Records are versioned, creating version N+1 with before/after snapshots.
    """
    __tablename__ = "correction_requests"

    enrollment_id = Column(String(36), ForeignKey("enrollments.id"), nullable=False, index=True)
    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=False, index=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(32), default="PENDING", nullable=False, index=True)  # PENDING, APPROVED, REJECTED
    reason_code = Column(String(64), nullable=False)
    explanation = Column(Text, nullable=False)
    proposed_changes = Column(JSON, nullable=False)
    previous_state = Column(JSON, nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    decision_reason = Column(Text, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    version_created = Column(Integer, nullable=True)

    enrollment = relationship("Enrollment")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by])
    institution = relationship("Institution")
