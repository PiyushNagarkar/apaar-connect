from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class Enrollment(Base, TimestampedUUIDMixin):
    """
    enrollments(student_id, institution_id, approval_id, academic_year, seat_type,
      category, admission_date, round, status, identity_status, authority_status,
      compliance_status, verified bool, version)

    Useful indexes: (institution_id, academic_year), (approval_id, seat_type, status)
    """
    __tablename__ = "enrollments"

    student_id = Column(String(36), ForeignKey("students.id"), nullable=False, index=True)
    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=False, index=True)
    approval_id = Column(String(36), ForeignKey("program_approvals.id"), nullable=False, index=True)
    academic_year = Column(String(16), nullable=False, index=True)
    seat_type = Column(String(64), nullable=False, index=True)  # REGULAR, NRI, SUPERNUMERARY_FN_OCI_PIO, etc.
    category = Column(String(32), nullable=False, index=True)   # OPEN, OBC_NCL, SC, ST, EWS, TFW, etc.
    admission_date = Column(DateTime(timezone=True), nullable=False)
    round = Column(String(32), default="1", nullable=False)
    status = Column(String(32), default="PROVISIONAL", nullable=False, index=True)
    identity_status = Column(String(32), default="PENDING", nullable=False)    # L1
    authority_status = Column(String(32), default="PENDING", nullable=False)   # L2
    compliance_status = Column(String(32), default="PENDING", nullable=False)  # L3
    verified = Column(Boolean, default=False, nullable=False, index=True)      # True only if all 3 pass
    version = Column(Integer, default=1, nullable=False)

    student = relationship("Student", back_populates="enrollments")
    institution = relationship("Institution", back_populates="enrollments")
    approval = relationship("ProgramApproval", back_populates="enrollments")
    credential = relationship("Credential", back_populates="enrollment", uselist=False)
    review_cases = relationship("ReviewCase", back_populates="enrollment")
    validation_issues = relationship("ValidationIssue", back_populates="enrollment")

    __table_args__ = (
        Index("idx_enrollments_inst_ay", "institution_id", "academic_year"),
        Index("idx_enrollments_approval_seat_status", "approval_id", "seat_type", "status"),
    )
