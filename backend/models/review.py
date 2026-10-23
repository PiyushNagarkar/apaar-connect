from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class ReviewCase(Base, TimestampedUUIDMixin):
    """
    review_cases(type, severity, priority, enrollment_id, assigned_to, status, decision,
      decision_reason, evidence JSON, due_at)
    Rule 6: Scores only PRIORITISE human review, and every score shows its components/reason codes.
    """
    __tablename__ = "review_cases"

    type = Column(String(64), nullable=False, index=True)  # DUPLICATE_MATCH, SEAT_OVERFLOW, IDENTITY_MISMATCH
    severity = Column(String(32), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    priority = Column(Float, default=50.0, nullable=False, index=True)  # 0 to 100 queue sort (Rule 6)
    enrollment_id = Column(String(36), ForeignKey("enrollments.id"), nullable=False, index=True)
    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=True, index=True)
    assigned_to = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    status = Column(String(32), default="OPEN", nullable=False, index=True)  # OPEN, ASSIGNED, AWAITING_INSTITUTION, UNDER_DECISION, RESOLVED, ESCALATED
    decision = Column(String(32), nullable=True)  # DATA_ENTRY_ERROR, LEGITIMATE_SEPARATE_ENROLMENT, WITHDRAW_ONE_RECORD, CONFIRM, REJECT, ESCALATE
    decision_reason = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)

    enrollment = relationship("Enrollment", back_populates="review_cases")
    institution = relationship("Institution")
    assignee = relationship("User", back_populates="assigned_reviews")
