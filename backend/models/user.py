from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class User(Base, TimestampedUUIDMixin):
    """
    users(email, password_hash, role, institution_id nullable, is_active)
    """
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(64), nullable=False, index=True)  # AICTE_ADMIN, AICTE_REVIEWER, INSTITUTION_ADMIN, etc.
    institution_id = Column(String(36), ForeignKey("institutions.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    institution = relationship("Institution", back_populates="users")
    submissions = relationship("Submission", back_populates="uploader")
    assigned_reviews = relationship("ReviewCase", back_populates="assignee")
