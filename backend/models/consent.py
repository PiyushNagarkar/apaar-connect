from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class ConsentRecord(Base, TimestampedUUIDMixin):
    """
    consent_records(student_id, purpose, consent_status, status, reference, timestamp)
    Tracks student consent decisions: GRANTED | PENDING | WITHDRAWN | NOT_REQUIRED.
    Purposes: ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING.
    """
    __tablename__ = "consent_records"

    student_id = Column(String(36), ForeignKey("students.id"), nullable=False, index=True)
    purpose = Column(String(128), nullable=False, index=True)  # ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING
    status = Column(String(32), default="GRANTED", nullable=False)  # GRANTED, PENDING, WITHDRAWN, NOT_REQUIRED
    consent_status = Column(String(32), default="GRANTED", nullable=False)  # Explicit field matching requirement
    reference = Column(String(128), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)

    student = relationship("Student", back_populates="consent_records")


class ProcessingBasisRecord(Base, TimestampedUUIDMixin):
    """
    processing_basis_records(institution_id, student_id, basis_type, statute_reference,
      purpose, description, valid_from, valid_until, is_active, created_by)
    Kept strictly separate from student consent (separate record type).
    Establishes statutory/legal authority for retaining and processing admission data
    even when student consent is WITHDRAWN.
    """
    __tablename__ = "processing_basis_records"

    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=True, index=True)
    student_id = Column(String(36), ForeignKey("students.id"), nullable=True, index=True)
    basis_type = Column(String(64), nullable=False, index=True)  # STATUTORY_MANDATE, LEGAL_OBLIGATION, PUBLIC_INTEREST, REGULATORY_COMPLIANCE
    statute_reference = Column(String(128), nullable=False, index=True)  # e.g., "AICTE Act 1987 Sec 10(k)", "DPDP Act 2023 Sec 7(b)"
    purpose = Column(String(128), nullable=False, index=True)  # ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING
    description = Column(Text, nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(64), nullable=True)

    institution = relationship("Institution")
    student = relationship("Student")
