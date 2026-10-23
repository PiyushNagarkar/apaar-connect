from sqlalchemy import Column, String, Date, Text, Index
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class Student(Base, TimestampedUUIDMixin):
    """
    students(apaar_encrypted, apaar_hash, apaar_masked, name, name_normalized, dob, gender,
      mobile_hash, mobile_last4, email_hash, consent_status)
    Useful index: apaar_hash
    """
    __tablename__ = "students"

    apaar_encrypted = Column(Text, nullable=False)  # AES-256-GCM (Rule 10)
    apaar_hash = Column(String(64), nullable=False, index=True)  # Keyed blind index (Rule 10)
    apaar_masked = Column(String(32), nullable=False)  # XXXX-XXXX-1234
    name = Column(String(255), nullable=False, index=True)
    name_normalized = Column(String(255), nullable=False, index=True)
    dob = Column(Date, nullable=False, index=True)
    gender = Column(String(16), nullable=False)
    mobile_hash = Column(String(64), nullable=True, index=True)
    mobile_last4 = Column(String(8), nullable=True)
    email_hash = Column(String(64), nullable=True)
    consent_status = Column(String(32), default="GRANTED", nullable=False)

    enrollments = relationship("Enrollment", back_populates="student")
    identity_checks = relationship("IdentityCheck", back_populates="student")
    consent_records = relationship("ConsentRecord", back_populates="student")

    __table_args__ = (
        Index("idx_students_apaar_hash", "apaar_hash"),
        Index("idx_students_dob", "dob"),
        Index("idx_students_mobile_hash", "mobile_hash"),
    )
