from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, Index
from sqlalchemy.orm import relationship
import enum
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class ApprovalStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"


class ProgramApproval(Base, TimestampedUUIDMixin):
    """
    program_approvals(institution_id, programme, branch, campus, shift, academic_year,
      approval_ref, version, status[DRAFT|FROZEN], frozen_at, frozen_by, supersedes_id)
    """
    __tablename__ = "program_approvals"

    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=False, index=True)
    programme = Column(String(128), nullable=False)  # e.g., ENGINEERING_AND_TECHNOLOGY
    branch = Column(String(128), nullable=False)     # e.g., COMPUTER_SCIENCE_AND_ENGINEERING
    campus = Column(String(64), default="MAIN", nullable=False)
    shift = Column(String(32), default="FIRST", nullable=False)
    academic_year = Column(String(16), nullable=False, index=True)  # e.g., 2024-2025
    approval_ref = Column(String(128), nullable=False, index=True)  # EoA Order Number
    version = Column(Integer, default=1, nullable=False)
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.DRAFT, nullable=False, index=True)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    frozen_by = Column(String(64), nullable=True)
    supersedes_id = Column(String(36), ForeignKey("program_approvals.id"), nullable=True)

    institution = relationship("Institution", back_populates="program_approvals")
    seat_allocations = relationship("SeatAllocation", back_populates="approval", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="approval")
    superseded_by = relationship("ProgramApproval", remote_side="ProgramApproval.id")

    __table_args__ = (
        Index("idx_prog_approvals_lookup", "institution_id", "programme", "branch", "academic_year"),
    )
