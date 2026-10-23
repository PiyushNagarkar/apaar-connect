"""
RuleVersionConfig Model:
Stores AICTE Approval Process Handbook rule versions and category definitions.
Rule 3: Seat categories & quota rules are defined centrally.
"""
from sqlalchemy import Column, String, Boolean, JSON, Text, Float
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class RuleVersionConfig(Base, TimestampedUUIDMixin):
    __tablename__ = "rule_version_configs"

    rule_version = Column(String(64), unique=True, nullable=False, index=True)
    academic_year = Column(String(16), nullable=False, index=True)
    description = Column(String(255), nullable=True)
    allowed_seat_types = Column(JSON, nullable=False)
    handbook_reference = Column(String(128), default="AICTE Approval Process Handbook (APH)")
    handbook_note = Column(
        Text,
        default="Verify against the current AICTE Approval Process Handbook.",
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)


class RuleSeverityConfig(Base, TimestampedUUIDMixin):
    """
    rule_severity_configs(rule_code, severity, is_active, description)
    Allows runtime configuration of rule severity levels.
    """
    __tablename__ = "rule_severity_configs"

    rule_code = Column(String(64), unique=True, nullable=False, index=True)
    severity = Column(String(32), nullable=False)  # INFO, WARNING, ERROR, HIGH, CRITICAL, REGULATORY_ALERT
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(String(255), nullable=True)


class RiskScoreConfig(Base, TimestampedUUIDMixin):
    """
    risk_score_configs(rule_version, weight_s, weight_d, weight_l, weight_c, weight_i, is_active, description)
    Stores configurable weights for the Review-Priority Risk Score R = w1*S + w2*D + w3*L + w4*C + w5*I.
    Default weights: 0.30 (S), 0.25 (D), 0.15 (L), 0.10 (C), 0.20 (I).
    """
    __tablename__ = "risk_score_configs"

    rule_version = Column(String(64), unique=True, nullable=False, index=True)
    weight_s = Column(Float, default=0.30, nullable=False)  # seat-exception severity
    weight_d = Column(Float, default=0.25, nullable=False)  # duplicate-case severity
    weight_l = Column(Float, default=0.15, nullable=False)  # late-submission rate
    weight_c = Column(Float, default=0.10, nullable=False)  # correction rate after first submission
    weight_i = Column(Float, default=0.20, nullable=False)  # identity-failure rate
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(String(255), nullable=True)


