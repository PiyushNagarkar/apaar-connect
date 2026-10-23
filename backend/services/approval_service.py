"""
Approval Management Service:
Implements:
- Approval creation & DRAFT editing
- FREEZE operation (immutable approval and allocations)
- N+1 Versioning with supersedes_id and mandatory change reason
- CSV Import with row-level validation and preview
- Comprehensive Seat Matrix calculation with zero-approved handling and utilisation %
- Rule version config management
"""
import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import event, func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

from backend.database import Base
from backend.models.institution import Institution
from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.seat import SeatAllocation, SeatType
from backend.models.enrollment import Enrollment
from backend.models.version import RecordVersion
from backend.models.rule_config import RuleVersionConfig
from backend.schemas.errors import AppException, NotFoundError
from backend.services.audit import record_audit_event

DEFAULT_RULE_VERSION = "AICTE_HANDBOOK_2024_25_V1"
HANDBOOK_NOTE = "Verify against the current AICTE Approval Process Handbook."

ALL_SEAT_TYPES = [
    SeatType.REGULAR,
    SeatType.NRI,
    SeatType.SUPERNUMERARY_FN_OCI_PIO,
    SeatType.SUPERNUMERARY_GULF_WORKER_CHILD,
    SeatType.OTHER,
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ORM Guards: Enforce immutability on FROZEN ProgramApprovals & SeatAllocations
# ---------------------------------------------------------------------------

@event.listens_for(ProgramApproval, "before_update")
def guard_frozen_approval_update(mapper, connection, target):
    """DB/ORM Guard: Rejects updates to already FROZEN approval rows."""
    status_history = get_history(target, "status")
    # If the row was already FROZEN prior to this update
    if not status_history.has_changes() and target.status == ApprovalStatus.FROZEN:
        raise AppException(
            code="APPROVAL_FROZEN_IMMUTABLE",
            message=f"Approval '{target.approval_ref}' is FROZEN and immutable. Any corrections must supersede with version {target.version + 1}.",
            status_code=409,
        )
    # Reverting from FROZEN to DRAFT is strictly forbidden
    if status_history.has_changes():
        old_val = status_history.deleted[0] if status_history.deleted else None
        if old_val == ApprovalStatus.FROZEN:
            raise AppException(
                code="INVALID_STATE_TRANSITION",
                message="Cannot revert a FROZEN approval back to DRAFT. Corrections must create version N+1.",
                status_code=409,
            )


@event.listens_for(SeatAllocation, "before_update")
def guard_frozen_seat_allocation_update(mapper, connection, target):
    """DB/ORM Guard: Rejects updates to allocations of a FROZEN approval."""
    if target.approval and target.approval.status == ApprovalStatus.FROZEN:
        raise AppException(
            code="APPROVAL_FROZEN_IMMUTABLE",
            message=f"Seat allocations for frozen approval '{target.approval.approval_ref}' are immutable.",
            status_code=409,
        )


@event.listens_for(SeatAllocation, "before_delete")
def guard_frozen_seat_allocation_delete(mapper, connection, target):
    """DB/ORM Guard: Rejects deletion of allocations of a FROZEN approval."""
    if target.approval and target.approval.status == ApprovalStatus.FROZEN:
        raise AppException(
            code="APPROVAL_FROZEN_IMMUTABLE",
            message="Cannot delete seat allocations of a frozen approval.",
            status_code=409,
        )


# ---------------------------------------------------------------------------
# Service Helpers & Snapshot Generation
# ---------------------------------------------------------------------------

def approval_to_snapshot(approval: ProgramApproval) -> dict:
    """Serializes approval and its seat allocations for immutable versioning."""
    allocations_dict = {}
    for alloc in approval.seat_allocations:
        seat_key = alloc.seat_type.value if hasattr(alloc.seat_type, "value") else str(alloc.seat_type)
        allocations_dict[seat_key] = alloc.approved_count

    return {
        "id": str(approval.id),
        "institution_id": str(approval.institution_id),
        "programme": approval.programme,
        "branch": approval.branch,
        "campus": approval.campus,
        "shift": approval.shift,
        "academic_year": approval.academic_year,
        "approval_ref": approval.approval_ref,
        "version": approval.version,
        "status": approval.status.value if hasattr(approval.status, "value") else str(approval.status),
        "frozen_at": approval.frozen_at.isoformat() if approval.frozen_at else None,
        "frozen_by": approval.frozen_by,
        "supersedes_id": str(approval.supersedes_id) if approval.supersedes_id else None,
        "seat_allocations": allocations_dict,
    }


# ---------------------------------------------------------------------------
# Core Business Methods
# ---------------------------------------------------------------------------

def create_approval(
    db: Session,
    institution_id: str,
    programme: str,
    branch: str,
    academic_year: str,
    approval_ref: str,
    campus: str = "MAIN",
    shift: str = "FIRST",
    allocations: Optional[Dict[str, int]] = None,
    rule_version: str = DEFAULT_RULE_VERSION,
    actor_id: str = "admin@aicte.gov.in",
) -> ProgramApproval:
    """
    Creates a new DRAFT approval with one seat_allocation row per seat_type.
    """
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise NotFoundError(f"Institution with id '{institution_id}' was not found.")

    approval = ProgramApproval(
        institution_id=institution_id,
        programme=programme.strip(),
        branch=branch.strip(),
        campus=campus.strip(),
        shift=shift.strip(),
        academic_year=academic_year.strip(),
        approval_ref=approval_ref.strip(),
        version=1,
        status=ApprovalStatus.DRAFT,
        supersedes_id=None,
    )
    db.add(approval)
    db.flush()

    allocations = allocations or {}
    for seat_type in ALL_SEAT_TYPES:
        st_key = seat_type.value
        count = int(allocations.get(st_key, allocations.get(st_key.lower(), 0)))
        seat_alloc = SeatAllocation(
            approval_id=approval.id,
            seat_type=seat_type,
            approved_count=max(0, count),
            rule_version=rule_version,
        )
        db.add(seat_alloc)

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="APPROVAL_CREATE",
        entity_type="PROGRAM_APPROVAL",
        entity_id=str(approval.id),
        reason=f"Created DRAFT program approval {approval.approval_ref} v1",
    )
    db.commit()
    db.refresh(approval)
    return approval


def update_draft_approval(
    db: Session,
    approval_id: str,
    updates: Dict[str, Any],
    allocations: Optional[Dict[str, int]] = None,
    actor_id: str = "admin@aicte.gov.in",
) -> ProgramApproval:
    """
    Edits a DRAFT approval. If approval is FROZEN, rejects with HTTP 409.
    """
    approval = db.query(ProgramApproval).filter(ProgramApproval.id == approval_id).first()
    if not approval:
        raise NotFoundError(f"Approval with id '{approval_id}' was not found.")

    if approval.status == ApprovalStatus.FROZEN:
        raise AppException(
            code="APPROVAL_FROZEN_IMMUTABLE",
            message=f"Cannot edit approval '{approval.approval_ref}' because it is FROZEN. You must create version {approval.version + 1} with supersedes_id.",
            status_code=409,
        )

    # Apply scalar field updates
    for field in ["programme", "branch", "campus", "shift", "academic_year", "approval_ref"]:
        if field in updates and updates[field] is not None:
            setattr(approval, field, updates[field].strip())

    # Update allocations if provided
    if allocations:
        for seat_alloc in approval.seat_allocations:
            st_key = seat_alloc.seat_type.value
            if st_key in allocations:
                seat_alloc.approved_count = max(0, int(allocations[st_key]))

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="APPROVAL_UPDATE_DRAFT",
        entity_type="PROGRAM_APPROVAL",
        entity_id=str(approval.id),
        reason="Updated draft approval parameters",
    )
    db.commit()
    db.refresh(approval)
    return approval


def freeze_approval(
    db: Session,
    approval_id: str,
    actor_email: str,
    actor_id: str,
) -> ProgramApproval:
    """
    Freezes a DRAFT approval, making it and its allocations immutable.
    Records snapshot in record_versions and an audit event.
    """
    approval = db.query(ProgramApproval).filter(ProgramApproval.id == approval_id).first()
    if not approval:
        raise NotFoundError(f"Approval with id '{approval_id}' was not found.")

    if approval.status == ApprovalStatus.FROZEN:
        return approval

    approval.status = ApprovalStatus.FROZEN
    approval.frozen_at = utc_now()
    approval.frozen_by = actor_email

    # Snapshot to RecordVersion
    snapshot = approval_to_snapshot(approval)
    version_record = RecordVersion(
        entity_type="PROGRAM_APPROVAL",
        entity_id=str(approval.id),
        version=approval.version,
        snapshot=snapshot,
        change_reason=f"Approval frozen and ratified by {actor_email}",
        actor_id=actor_id,
    )
    db.add(version_record)

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="APPROVAL_FREEZE",
        entity_type="PROGRAM_APPROVAL",
        entity_id=str(approval.id),
        reason=f"Frozen approval {approval.approval_ref} v{approval.version}",
    )
    db.commit()
    db.refresh(approval)
    return approval


def supersede_approval(
    db: Session,
    approval_id: str,
    change_reason: str,
    updates: Optional[Dict[str, Any]] = None,
    allocations: Optional[Dict[str, int]] = None,
    actor_email: str = "admin@aicte.gov.in",
    actor_id: str = "admin-01",
) -> ProgramApproval:
    """
    Creates version N+1 with supersedes_id pointing to the prior version.
    Mandatory change_reason must be provided. Old version stays readable and untouched.
    """
    if not change_reason or not change_reason.strip():
        raise AppException(
            code="MANDATORY_CHANGE_REASON_REQUIRED",
            message="A mandatory change reason is required to supersede an approval.",
            status_code=400,
            field="change_reason",
        )

    old_approval = db.query(ProgramApproval).filter(ProgramApproval.id == approval_id).first()
    if not old_approval:
        raise NotFoundError(f"Approval with id '{approval_id}' was not found.")

    updates = updates or {}
    new_version_num = old_approval.version + 1

    new_approval = ProgramApproval(
        institution_id=updates.get("institution_id", old_approval.institution_id),
        programme=updates.get("programme", old_approval.programme),
        branch=updates.get("branch", old_approval.branch),
        campus=updates.get("campus", old_approval.campus),
        shift=updates.get("shift", old_approval.shift),
        academic_year=updates.get("academic_year", old_approval.academic_year),
        approval_ref=updates.get("approval_ref", old_approval.approval_ref),
        version=new_version_num,
        status=ApprovalStatus.DRAFT,
        supersedes_id=old_approval.id,
    )
    db.add(new_approval)
    db.flush()

    # Replicate or update allocations
    old_allocs = {a.seat_type.value: a.approved_count for a in old_approval.seat_allocations}
    allocations = allocations or {}
    for seat_type in ALL_SEAT_TYPES:
        st_key = seat_type.value
        count = allocations.get(st_key, old_allocs.get(st_key, 0))
        new_alloc = SeatAllocation(
            approval_id=new_approval.id,
            seat_type=seat_type,
            approved_count=max(0, count),
            rule_version=old_approval.seat_allocations[0].rule_version if old_approval.seat_allocations else DEFAULT_RULE_VERSION,
        )
        db.add(new_alloc)

    # Record version entry
    version_record = RecordVersion(
        entity_type="PROGRAM_APPROVAL",
        entity_id=str(new_approval.id),
        version=new_version_num,
        snapshot=approval_to_snapshot(new_approval),
        change_reason=change_reason.strip(),
        actor_id=actor_id,
    )
    db.add(version_record)

    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="APPROVAL_SUPERSEDE",
        entity_type="PROGRAM_APPROVAL",
        entity_id=str(new_approval.id),
        reason=f"Created v{new_version_num} superseding {old_approval.id}: {change_reason.strip()}",
    )
    db.commit()
    db.refresh(new_approval)
    return new_approval


def get_approval_history(db: Session, approval_id: str) -> Dict[str, Any]:
    """
    Returns the complete version chain (history diff) of an approval.
    Traverses backwards and forwards through supersedes_id.
    """
    current = db.query(ProgramApproval).filter(ProgramApproval.id == approval_id).first()
    if not current:
        raise NotFoundError(f"Approval with id '{approval_id}' was not found.")

    # Find root approval (version 1)
    root = current
    while root.supersedes_id:
        parent = db.query(ProgramApproval).filter(ProgramApproval.id == root.supersedes_id).first()
        if not parent:
            break
        root = parent

    # Traverse forward from root
    chain: List[ProgramApproval] = [root]
    while True:
        child = db.query(ProgramApproval).filter(ProgramApproval.supersedes_id == chain[-1].id).first()
        if not child:
            break
        chain.append(child)

    # Build history list with diffs
    history_items = []
    prev_snapshot = None

    for item in chain:
        curr_snapshot = approval_to_snapshot(item)
        
        # Fetch recorded change reason from RecordVersion
        rec_ver = (
            db.query(RecordVersion)
            .filter(
                RecordVersion.entity_type == "PROGRAM_APPROVAL",
                RecordVersion.entity_id == str(item.id),
                RecordVersion.version == item.version,
            )
            .first()
        )
        reason = rec_ver.change_reason if rec_ver else ("Initial creation" if item.version == 1 else "Correction")

        diff = {}
        if prev_snapshot:
            # Calculate seat differences
            curr_seats = curr_snapshot["seat_allocations"]
            prev_seats = prev_snapshot["seat_allocations"]
            seat_diff = {}
            for st in ALL_SEAT_TYPES:
                k = st.value
                c_val = curr_seats.get(k, 0)
                p_val = prev_seats.get(k, 0)
                if c_val != p_val:
                    seat_diff[k] = {"old": p_val, "new": c_val, "delta": c_val - p_val}
            if seat_diff:
                diff["seat_allocations"] = seat_diff

            # Calculate field differences
            for field in ["programme", "branch", "campus", "shift", "approval_ref", "academic_year"]:
                if curr_snapshot[field] != prev_snapshot[field]:
                    diff[field] = {"old": prev_snapshot[field], "new": curr_snapshot[field]}

        history_items.append({
            "version": item.version,
            "id": str(item.id),
            "status": item.status.value,
            "approval_ref": item.approval_ref,
            "academic_year": item.academic_year,
            "programme": item.programme,
            "branch": item.branch,
            "frozen_at": item.frozen_at.isoformat() if item.frozen_at else None,
            "frozen_by": item.frozen_by,
            "supersedes_id": str(item.supersedes_id) if item.supersedes_id else None,
            "change_reason": reason,
            "seat_allocations": curr_snapshot["seat_allocations"],
            "diff_from_previous": diff,
        })
        prev_snapshot = curr_snapshot

    return {
        "approval_ref": current.approval_ref,
        "current_id": str(current.id),
        "total_versions": len(history_items),
        "history": history_items,
    }


def import_approvals_csv(
    db: Session,
    csv_text: str,
    commit: bool = False,
    actor_id: str = "admin@aicte.gov.in",
) -> Dict[str, Any]:
    """
    Imports approvals from CSV with row validation and preview.
    Expected CSV columns:
    institution_code,programme,branch,campus,shift,academic_year,approval_ref,regular_seats,nri_seats,fn_seats,gulf_seats,other_seats,rule_version
    """
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    preview_data = []
    errors = []
    valid_count = 0
    invalid_count = 0
    created_ids = []

    for idx, row in enumerate(reader, start=1):
        row_clean = {k.strip(): (v.strip() if v else "") for k, v in row.items()}
        inst_code = row_clean.get("institution_code")
        programme = row_clean.get("programme")
        branch = row_clean.get("branch")
        ay = row_clean.get("academic_year")
        ref = row_clean.get("approval_ref")

        row_errors = []
        if not inst_code:
            row_errors.append("Missing mandatory 'institution_code'")
        if not programme:
            row_errors.append("Missing mandatory 'programme'")
        if not branch:
            row_errors.append("Missing mandatory 'branch'")
        if not ay:
            row_errors.append("Missing mandatory 'academic_year'")
        if not ref:
            row_errors.append("Missing mandatory 'approval_ref'")

        inst = db.query(Institution).filter(Institution.code == inst_code).first() if inst_code else None
        if inst_code and not inst:
            row_errors.append(f"Institution with code '{inst_code}' not found")

        # Parse seat counts
        allocations = {}
        seat_mapping = {
            "regular_seats": SeatType.REGULAR.value,
            "nri_seats": SeatType.NRI.value,
            "fn_seats": SeatType.SUPERNUMERARY_FN_OCI_PIO.value,
            "gulf_seats": SeatType.SUPERNUMERARY_GULF_WORKER_CHILD.value,
            "other_seats": SeatType.OTHER.value,
        }
        for csv_col, seat_val in seat_mapping.items():
            val = row_clean.get(csv_col, "0")
            try:
                allocations[seat_val] = max(0, int(val or 0))
            except ValueError:
                row_errors.append(f"Invalid integer count for '{csv_col}': {val}")

        is_valid = len(row_errors) == 0
        if is_valid:
            valid_count += 1
            if commit and inst:
                appr = create_approval(
                    db=db,
                    institution_id=str(inst.id),
                    programme=programme,
                    branch=branch,
                    academic_year=ay,
                    approval_ref=ref,
                    campus=row_clean.get("campus", "MAIN"),
                    shift=row_clean.get("shift", "FIRST"),
                    allocations=allocations,
                    rule_version=row_clean.get("rule_version", DEFAULT_RULE_VERSION),
                    actor_id=actor_id,
                )
                created_ids.append(str(appr.id))
        else:
            invalid_count += 1
            errors.append({"row_number": idx, "row_data": row_clean, "errors": row_errors})

        preview_data.append({
            "row_number": idx,
            "institution_code": inst_code,
            "programme": programme,
            "branch": branch,
            "academic_year": ay,
            "approval_ref": ref,
            "allocations": allocations,
            "is_valid": is_valid,
            "errors": row_errors,
        })

    return {
        "commit": commit,
        "total_rows": len(preview_data),
        "valid_rows": valid_count,
        "invalid_rows": invalid_count,
        "created_approvals_count": len(created_ids),
        "created_ids": created_ids,
        "preview": preview_data,
        "errors": errors,
    }


def calculate_seat_matrix(
    db: Session,
    institution_id: Optional[str] = None,
    academic_year: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes real-time seat matrix per seat_type:
    - approved
    - confirmed+active occupied
    - provisional (shown separately)
    - available
    - utilisation %
    Explicitly handles approved=0 (any admissions flagged "no approval for this category").
    Includes visible handbook note.
    """
    query = db.query(ProgramApproval)
    if institution_id:
        query = query.filter(ProgramApproval.institution_id == institution_id)
    if academic_year:
        query = query.filter(ProgramApproval.academic_year == academic_year)
    if approval_id:
        query = query.filter(ProgramApproval.id == approval_id)

    approvals = query.all()
    approval_ids = [a.id for a in approvals]

    # Query enrollments count grouped by (seat_type, status)
    enrollment_counts = {st.value: {"confirmed": 0, "provisional": 0} for st in ALL_SEAT_TYPES}

    if approval_ids:
        rows = (
            db.query(
                Enrollment.seat_type,
                Enrollment.status,
                func.count(Enrollment.id).label("total"),
            )
            .filter(Enrollment.approval_id.in_(approval_ids))
            .group_by(Enrollment.seat_type, Enrollment.status)
            .all()
        )
        for seat_type_val, st_val, count in rows:
            if seat_type_val in enrollment_counts:
                if st_val in ["CONFIRMED", "ADMITTED", "VERIFIED"]:
                    enrollment_counts[seat_type_val]["confirmed"] += count
                elif st_val == "PROVISIONAL":
                    enrollment_counts[seat_type_val]["provisional"] += count

    # Sum approved counts per seat_type
    matrix = []
    total_approved = 0
    total_confirmed = 0
    total_provisional = 0

    for seat_type in ALL_SEAT_TYPES:
        st_key = seat_type.value
        approved = sum(
            alloc.approved_count
            for a in approvals
            for alloc in a.seat_allocations
            if alloc.seat_type == seat_type
        )
        confirmed = enrollment_counts[st_key]["confirmed"]
        provisional = enrollment_counts[st_key]["provisional"]
        occupied = confirmed + provisional
        available = max(0, approved - occupied)

        # Utilisation % calculation
        if approved > 0:
            utilisation_pct = round((occupied / approved) * 100.0, 2)
            zero_approved_warning = None
        else:
            utilisation_pct = 0.0
            zero_approved_warning = (
                "no approval for this category" if occupied > 0 else None
            )

        total_approved += approved
        total_confirmed += confirmed
        total_provisional += provisional

        matrix.append({
            "seat_type": st_key,
            "approved": approved,
            "confirmed_active": confirmed,
            "provisional": provisional,
            "occupied_total": occupied,
            "available": available,
            "utilisation_pct": utilisation_pct,
            "warning": zero_approved_warning,
        })

    total_occupied = total_confirmed + total_provisional
    total_utilisation = round((total_occupied / total_approved) * 100.0, 2) if total_approved > 0 else 0.0

    return {
        "rule_version": DEFAULT_RULE_VERSION,
        "handbook_note": HANDBOOK_NOTE,
        "institution_id": institution_id,
        "academic_year": academic_year,
        "matched_approvals_count": len(approvals),
        "summary": {
            "total_approved": total_approved,
            "total_confirmed_active": total_confirmed,
            "total_provisional": total_provisional,
            "total_occupied": total_occupied,
            "total_available": max(0, total_approved - total_occupied),
            "overall_utilisation_pct": total_utilisation,
        },
        "seat_matrix": matrix,
    }
