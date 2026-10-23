from sqlalchemy import Column, String
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class Institution(Base, TimestampedUUIDMixin):
    """
    institutions(code, name, status)
    """
    __tablename__ = "institutions"

    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, SUSPENDED, DEBARRED

    users = relationship("User", back_populates="institution")
    program_approvals = relationship("ProgramApproval", back_populates="institution")
    enrollments = relationship("Enrollment", back_populates="institution")
    submissions = relationship("Submission", back_populates="institution")
