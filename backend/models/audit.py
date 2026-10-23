
from sqlalchemy import Column, String, Text, event, DDL
from backend.database import Base, engine
from backend.models.base import TimestampedUUIDMixin


class AuditEvent(Base, TimestampedUUIDMixin):
    """
    Append-only audit events.
    UPDATE and DELETE operations are prohibited.
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
    hash = Column(String(64), nullable=True)


class AuditAppendOnlyViolation(PermissionError):
    """Raised when an UPDATE or DELETE is attempted on audit_events."""
    pass


@event.listens_for(AuditEvent, "before_update")
def _audit_prevent_update(mapper, connection, target):
    raise AuditAppendOnlyViolation(
        "audit_events is append-only: UPDATE operations are strictly prohibited."
    )


@event.listens_for(AuditEvent, "before_delete")
def _audit_prevent_delete(mapper, connection, target):
    raise AuditAppendOnlyViolation(
        "audit_events is append-only: DELETE operations are strictly prohibited."
    )


# SQLite-only triggers. PostgreSQL does not support this SQLite syntax.
if engine.dialect.name == "sqlite":
    sqlite_no_update_trigger = DDL(
        """
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT,
                'audit_events is append-only: UPDATE operations are strictly prohibited');
        END;
        """
    )

    sqlite_no_delete_trigger = DDL(
        """
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
        BEFORE DELETE ON audit_events
        BEGIN
            SELECT RAISE(ABORT,
                'audit_events is append-only: DELETE operations are strictly prohibited');
        END;
        """
    )

    event.listen(AuditEvent.__table__, "after_create", sqlite_no_update_trigger)
    event.listen(AuditEvent.__table__, "after_create", sqlite_no_delete_trigger)
