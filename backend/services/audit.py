"""
Legacy Audit Service forwarder (backend/services/audit.py).
Re-exports from backend.services.audit_service.
"""
from backend.services.audit_service import (
    calculate_audit_hash,
    record_audit_event,
    get_audit_events,
    verify_audit_hash_chain,
    get_retention_policies,
    update_retention_policy,
)

__all__ = [
    "calculate_audit_hash",
    "record_audit_event",
    "get_audit_events",
    "verify_audit_hash_chain",
    "get_retention_policies",
    "update_retention_policy",
]
