from sqlalchemy import Column, String, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class DuplicateCandidate(Base, TimestampedUUIDMixin):
    """
    duplicate_candidates(enrollment_a, enrollment_b, match_type, score, reasons JSON, status)
    Rule 4: Never auto-merges, auto-rejects or auto-accuses.
    """
    __tablename__ = "duplicate_candidates"

    enrollment_a = Column(String(36), ForeignKey("enrollments.id"), nullable=False, index=True)
    enrollment_b = Column(String(36), ForeignKey("enrollments.id"), nullable=False, index=True)
    match_type = Column(String(64), nullable=False)  # EXACT_APAAR, CROSS_INSTITUTION, FUZZY_NAME_DOB
    score = Column(Float, nullable=False, default=1.0)
    reasons = Column(JSON, nullable=False)
    status = Column(String(32), default="DETECTED", nullable=False)  # DETECTED, UNDER_REVIEW, RESOLVED, DISMISSED

    enrollment_first = relationship("Enrollment", foreign_keys=[enrollment_a])
    enrollment_second = relationship("Enrollment", foreign_keys=[enrollment_b])
