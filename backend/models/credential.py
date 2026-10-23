from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON, Integer, Boolean
from sqlalchemy.orm import relationship
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class Credential(Base, TimestampedUUIDMixin):
    """
    credentials(enrollment_id, public_ref, payload JSON, signature, key_id, expires_at,
      revoked_at, revoke_reason, status)
    Constraint: public_ref unique
    Rule 10: Privacy-minimal, no raw APAAR ID in payload.
    """
    __tablename__ = "credentials"

    enrollment_id = Column(String(36), ForeignKey("enrollments.id"), unique=True, nullable=False, index=True)
    public_ref = Column(String(128), unique=True, nullable=False, index=True)  # Public unique reference
    payload = Column(JSON, nullable=False)  # Privacy-minimal non-sensitive claims
    signature = Column(Text, nullable=False)  # Cryptographic Ed25519 signature
    key_id = Column(String(64), default="AICTE-ED25519-2025-V1", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoke_reason = Column(Text, nullable=True)
    status = Column(String(32), default="ACTIVE", nullable=False, index=True)  # ACTIVE, REVOKED, EXPIRED

    enrollment = relationship("Enrollment", back_populates="credential")


class RegisteredVerifier(Base, TimestampedUUIDMixin):
    """
    Registered third-party verifier entity (employers, universities, screening agencies).
    Enforces API key auth, rate limiting, and declared purpose.
    """
    __tablename__ = "registered_verifiers"

    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=False, index=True)
    declared_purpose = Column(String(128), nullable=False)  # e.g., EMPLOYMENT_VERIFICATION, EDUCATION_VERIFICATION
    api_key_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hash of API key
    api_key_prefix = Column(String(16), nullable=False)  # First 10 chars (e.g., ak_live_xxxx)
    rate_limit_per_minute = Column(Integer, default=60, nullable=False)
    allowed_fields = Column(JSON, nullable=True)  # List of permitted claim fields
    is_active = Column(Boolean, default=True, nullable=False)


class VerificationLog(Base, TimestampedUUIDMixin):
    """
    Audit log of verification attempts: who verified what, when, and what was disclosed.
    """
    __tablename__ = "verification_logs"

    reference = Column(String(128), nullable=False, index=True)
    verifier_class = Column(String(32), nullable=False, index=True)  # anonymous, registered_verifier, authorised_staff
    verifier_id = Column(String(64), nullable=True)
    verifier_name = Column(String(255), nullable=True)
    purpose = Column(String(128), nullable=True)
    result_status = Column(String(32), nullable=False, index=True)  # VALID, EXPIRED, REVOKED, MALFORMED, UNKNOWN, SERVICE_UNAVAILABLE
    disclosed_fields = Column(JSON, nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

