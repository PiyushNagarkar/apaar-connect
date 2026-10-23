from sqlalchemy import Column, String, Integer, Boolean, Text
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class RetentionPolicy(Base, TimestampedUUIDMixin):
    """
    retention_policies(record_category, retention_days, legal_basis, statutory_rule,
      action_on_expiry, description, is_active, updated_by)
    Configurable retention policy table for rejected, withdrawn, and duplicate records.
    Categories: REJECTED, WITHDRAWN, DUPLICATE, UNRESOLVED_EXCEPTIONS, AUDIT_LOGS.
    """
    __tablename__ = "retention_policies"

    record_category = Column(String(64), unique=True, nullable=False, index=True)  # REJECTED, WITHDRAWN, DUPLICATE, etc.
    retention_days = Column(Integer, nullable=False)  # Duration in days before record purging/archiving
    legal_basis = Column(String(255), nullable=False) # e.g. "AICTE Approval Process Handbook Clause 6.4"
    statutory_rule = Column(String(255), nullable=True) # e.g. "RULE_RETENTION_REJECTED_APPLICATIONS"
    action_on_expiry = Column(String(32), default="PURGE", nullable=False) # PURGE, ANONYMIZE, ARCHIVE
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_by = Column(String(64), nullable=True)
