"""
Seat Compliance Service (services/seat_compliance.py).
Computes quota compliance per seat type for a given program approval snapshot.
Core Rules:
- Counts only CONFIRMED + ACTIVE towards occupied seats.
- PROVISIONAL seats are tracked and reported separately.
- Status values: OK | NEAR_LIMIT (>= 95%) | AT_LIMIT (100%) | EXCEEDED (> 100%) | NO_APPROVAL.
- Isolation guarantee: Spare supernumerary seats must NOT absorb regular students.
- Lifecycle guarantee: Withdrawn/cancelled students are excluded, freeing up capacity.
"""
from typing import Any, Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.enrollment import Enrollment
from backend.models.seat import SeatAllocation, SeatType

STATUS_OK = "OK"
STATUS_NEAR_LIMIT = "NEAR_LIMIT"
STATUS_AT_LIMIT = "AT_LIMIT"
STATUS_EXCEEDED = "EXCEEDED"
STATUS_NO_APPROVAL = "NO_APPROVAL"

# Statuses that constitute actively occupied seats (counts only CONFIRMED + ACTIVE)
OCCUPIED_STATUSES = {"CONFIRMED", "ACTIVE"}
PROVISIONAL_STATUSES = {"PROVISIONAL"}


def determine_seat_status(occupied: int, approved: int, utilisation_pct: float) -> str:
    """Calculates status based on occupied count and approved capacity."""
    if approved <= 0:
        return STATUS_EXCEEDED if occupied > 0 else STATUS_AT_LIMIT
    if occupied > approved:
        return STATUS_EXCEEDED
    if occupied == approved:
        return STATUS_AT_LIMIT
    if utilisation_pct >= 95.0:
        return STATUS_NEAR_LIMIT
    return STATUS_OK


def calculate_approval_seat_compliance(
    db: Session,
    approval_id: str,
) -> Dict[str, Any]:
    """
    Computes per-seat-type utilization for a program approval.
    Returns:
    {
      "approval_id": "...",
      "programme": "...",
      "branch": "...",
      "academic_year": "...",
      "approval_status": "FROZEN",
      "overall_status": "OK" | "NEAR_LIMIT" | "AT_LIMIT" | "EXCEEDED" | "NO_APPROVAL",
      "by_seat_type": {
        "REGULAR": {
          "approved": 120,
          "confirmed": 100,
          "active": 20,
          "provisional": 5,
          "available": 0,
          "utilisation_pct": 100.0,
          "status": "AT_LIMIT"
        },
        ...
      },
      "totals": {
        "approved": 135,
        "confirmed": 110,
        "active": 25,
        "provisional": 5,
        "available": 0,
        "utilisation_pct": 100.0
      }
    }
    """
    approval = db.query(ProgramApproval).filter(ProgramApproval.id == approval_id).first()
    if not approval:
        return {
            "approval_id": approval_id,
            "overall_status": STATUS_NO_APPROVAL,
            "error": f"ProgramApproval '{approval_id}' was not found.",
            "by_seat_type": {},
            "totals": {
                "approved": 0,
                "confirmed": 0,
                "active": 0,
                "provisional": 0,
                "available": 0,
                "utilisation_pct": 0.0,
            },
        }

    allocations = (
        db.query(SeatAllocation)
        .filter(SeatAllocation.approval_id == approval_id)
        .all()
    )

    if not allocations:
        return {
            "approval_id": approval_id,
            "programme": approval.programme,
            "branch": approval.branch,
            "academic_year": approval.academic_year,
            "approval_status": approval.status.value if hasattr(approval.status, "value") else str(approval.status),
            "overall_status": STATUS_NO_APPROVAL,
            "error": "No seat allocations found for this approval.",
            "by_seat_type": {},
            "totals": {
                "approved": 0,
                "confirmed": 0,
                "active": 0,
                "provisional": 0,
                "available": 0,
                "utilisation_pct": 0.0,
            },
        }

    # Fetch all relevant enrollments for this approval
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.approval_id == approval_id)
        .all()
    )

    # Aggregate counts by seat_type and status
    counts_by_type: Dict[str, Dict[str, int]] = {}
    for alloc in allocations:
        st = alloc.seat_type.value if hasattr(alloc.seat_type, "value") else str(alloc.seat_type)
        counts_by_type[st] = {
            "approved": alloc.approved_count,
            "confirmed": 0,
            "active": 0,
            "provisional": 0,
        }

    for e in enrollments:
        st = e.seat_type
        if st not in counts_by_type:
            # Enrollment in an unallocated seat type
            counts_by_type[st] = {
                "approved": 0,
                "confirmed": 0,
                "active": 0,
                "provisional": 0,
            }

        status_norm = (e.status or "").upper()
        if status_norm == "CONFIRMED":
            counts_by_type[st]["confirmed"] += 1
        elif status_norm in ("ACTIVE", "ADMITTED"):
            counts_by_type[st]["active"] += 1
        elif status_norm in ("PROVISIONAL", "PENDING"):
            counts_by_type[st]["provisional"] += 1
        # Withdrawn, cancelled, or rejected students are intentionally excluded!

    by_seat_type: Dict[str, Dict[str, Any]] = {}
    has_exceeded = False
    has_at_limit = False
    has_near_limit = False

    tot_approved = 0
    tot_confirmed = 0
    tot_active = 0
    tot_provisional = 0

    for st, c in counts_by_type.items():
        approved = c["approved"]
        confirmed = c["confirmed"]
        active = c["active"]
        provisional = c["provisional"]
        occupied = confirmed + active  # Counts ONLY CONFIRMED + ACTIVE

        available = max(0, approved - occupied)
        util_pct = round((occupied / approved) * 100, 2) if approved > 0 else (100.0 if occupied > 0 else 0.0)
        st_status = determine_seat_status(occupied, approved, util_pct)

        if st_status == STATUS_EXCEEDED:
            has_exceeded = True
        elif st_status == STATUS_AT_LIMIT:
            has_at_limit = True
        elif st_status == STATUS_NEAR_LIMIT:
            has_near_limit = True

        by_seat_type[st] = {
            "seat_type": st,
            "approved": approved,
            "confirmed": confirmed,
            "active": active,
            "provisional": provisional,
            "occupied": occupied,
            "available": available,
            "utilisation_pct": util_pct,
            "status": st_status,
        }

        tot_approved += approved
        tot_confirmed += confirmed
        tot_active += active
        tot_provisional += provisional

    tot_occupied = tot_confirmed + tot_active
    tot_available = max(0, tot_approved - tot_occupied)
    tot_util_pct = round((tot_occupied / tot_approved) * 100, 2) if tot_approved > 0 else (100.0 if tot_occupied > 0 else 0.0)

    # Overall status: Any category exceeded makes the overall program EXCEEDED!
    # Spare supernumerary seats must NOT absorb regular students.
    if has_exceeded:
        overall_status = STATUS_EXCEEDED
    elif has_at_limit:
        overall_status = STATUS_AT_LIMIT
    elif has_near_limit:
        overall_status = STATUS_NEAR_LIMIT
    else:
        overall_status = STATUS_OK

    return {
        "approval_id": approval_id,
        "programme": approval.programme,
        "branch": approval.branch,
        "academic_year": approval.academic_year,
        "approval_status": approval.status.value if hasattr(approval.status, "value") else str(approval.status),
        "overall_status": overall_status,
        "by_seat_type": by_seat_type,
        "totals": {
            "approved": tot_approved,
            "confirmed": tot_confirmed,
            "active": tot_active,
            "provisional": tot_provisional,
            "occupied": tot_occupied,
            "available": tot_available,
            "utilisation_pct": tot_util_pct,
        },
    }
