from sqlalchemy import Column, String, Integer, ForeignKey, JSON, Enum, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
import enum
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class RowOutcome(str, enum.Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNPROCESSED = "UNPROCESSED"


class Submission(Base, TimestampedUUIDMixin):
    """
    submissions(institution_id, uploaded_by, round, status, idempotency_key, counts JSON)
    """
    __tablename__ = "submissions"

    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=False, index=True)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    academic_year = Column(String(16), nullable=True, index=True)
    programme = Column(String(128), nullable=True)
    round = Column(String(32), default="ROUND_1", nullable=False)
    status = Column(String(32), default="PENDING", nullable=False, index=True)  # PENDING, UPLOADED, VALIDATED, COMPLETED, PARTIALLY_FAILED, FAILED
    idempotency_key = Column(String(128), unique=True, nullable=True, index=True)
    counts = Column(JSON, nullable=True)  # {"total": X, "valid": Y, "invalid": Z, "committed": A, "failed": B}
    is_locked = Column(Boolean, default=False, nullable=False)
    lock_reason = Column(String(128), nullable=True)

    institution = relationship("Institution", back_populates="submissions")
    uploader = relationship("User", back_populates="submissions")
    rows = relationship("SubmissionRow", back_populates="submission", cascade="all, delete-orphan")


class SubmissionRow(Base, TimestampedUUIDMixin):
    """
    submission_rows(submission_id, row_number, raw JSON, normalized JSON,
      outcome[VALID|INVALID|COMMITTED|FAILED|UNPROCESSED], errors JSON, row_key)

    DB level enforcement:
    - Unique (submission_id, row_number)
    - Unique row_key
    """
    __tablename__ = "submission_rows"

    submission_id = Column(String(36), ForeignKey("submissions.id"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    raw = Column(JSON, nullable=False)
    normalized = Column(JSON, nullable=True)
    outcome = Column(Enum(RowOutcome), default=RowOutcome.UNPROCESSED, nullable=False, index=True)
    errors = Column(JSON, nullable=True)
    row_key = Column(String(128), unique=True, nullable=False, index=True)

    submission = relationship("Submission", back_populates="rows")
    validation_issues = relationship("ValidationIssue", back_populates="row")

    __table_args__ = (
        UniqueConstraint("submission_id", "row_number", name="uq_submission_row_number"),
        UniqueConstraint("row_key", name="uq_submission_row_key"),
    )
