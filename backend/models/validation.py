from sqlalchemy import Column, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class ValidationIssue(Base, TimestampedUUIDMixin):
    """
    validation_issues(enrollment_id|row_id, rule_code, severity, message, status)
    """
    __tablename__ = "validation_issues"

    enrollment_id = Column(String(36), ForeignKey("enrollments.id"), nullable=True, index=True)
    row_id = Column(String(36), ForeignKey("submission_rows.id"), nullable=True, index=True)
    rule_code = Column(String(64), nullable=False, index=True)  # e.g., RULE_SEAT_OVERFLOW, RULE_DUPLICATE_APAAR
    severity = Column(String(32), default="ERROR", nullable=False)  # INFO, WARNING, ERROR, CRITICAL
    message = Column(Text, nullable=False)
    status = Column(String(32), default="OPEN", nullable=False)  # OPEN, RESOLVED, SUPPRESSED

    enrollment = relationship("Enrollment", back_populates="validation_issues")
    row = relationship("SubmissionRow", back_populates="validation_issues")
