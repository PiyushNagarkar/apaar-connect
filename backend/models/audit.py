from sqlalchemy import Column, String, Text, event, DDL
from backend.database import Base
from backend.models.base import TimestampedUUIDMixin


class AuditEvent(Base, TimestampedUUIDMixin):
    """
    audit_events(actor_id, institution_id, action, entity_type, entity_id, reason,
      request_id, prev_hash nullable, hash nullable)
    Rule 9: Every state change writes an audit event.
    Append-only: The database role and ORM enforce INSERT and SELECT only.
    UPDATE and DELETE operations are strictly prohibited.
    """
    __tablename__ = "audit_events"

    actor_id = Column(String(64), nullable=False, index=True)
    institution_id = Column(String(36), nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String(64), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    request_id = Column(String(64), nullable=False, index=True)
    prev_hash = Column(String(64), nullable=True)
    hash = Column(String(64), nullable=True)  # Tamper-evident cryptographic hash SHA256(prev_hash + canonical_event)


# ---------------------------------------------------------------------------
# Append-Only Enforcements (ORM & Database Trigger Level)
# ---------------------------------------------------------------------------
class AuditAppendOnlyViolation(PermissionError):
    """Raised when an UPDATE or DELETE is attempted on append-only audit_events."""
    pass


@event.listens_for(AuditEvent, "before_update")
def _audit_prevent_update(mapper, connection, target):
    raise AuditAppendOnlyViolation("audit_events is append-only: UPDATE operations are strictly prohibited.")


@event.listens_for(AuditEvent, "before_delete")
def _audit_prevent_delete(mapper, connection, target):
    raise AuditAppendOnlyViolation("audit_events is append-only: DELETE operations are strictly prohibited.")


# SQLite / Engine-level triggers ensuring raw SQL queries also reject mutations
sqlite_no_update_trigger = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only: UPDATE operations are strictly prohibited');
    END;
    """
)

sqlite_no_delete_trigger = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only: DELETE operations are strictly prohibited');
    END;
    """
)

event.listen(AuditEvent.__table__, "after_create", sqlite_no_update_trigger)
event.listen(AuditEvent.__table__, "after_create", sqlite_no_delete_trigger)
