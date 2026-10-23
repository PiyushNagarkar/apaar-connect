"""
Statutory Reports Router (backend/api/reports.py).
Provides endpoints for generating and exporting regulatory reports:
- GET /api/reports/enrolment (alias /api/reports/enrollment)
- GET /api/reports/compliance
- GET /api/reports/data-quality
- GET /api/reports/duplicates
- GET /api/reports/timeliness
- GET /api/reports/audit
- GET /api/reports/{report_type}

Enforces:
- Server-side role and institutional scoping.
- Validated filters (institution, programme, year, round, status, date range).
- Standard metadata rows at the top of every CSV.
- Missing data exported as "N/A", never 0.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.errors import BadRequestError, ForbiddenError
from backend.security.authz import UserPrincipal, require_authenticated_user
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
)
from backend.services.reporting_service import (
    ALLOWED_REPORT_ROLES,
    generate_compliance_report_csv,
    generate_enrolment_report_csv,
    generate_data_quality_report_csv,
    generate_duplicates_report_csv,
    generate_timeliness_report_csv,
    generate_audit_report_csv,
    validate_report_access,
)

router = APIRouter(prefix="/reports", tags=["Statutory Reports"])


def resolve_report_csv(
    report_type: str,
    db: Session,
    user: UserPrincipal,
    institution_id: Optional[str],
    programme: Optional[str],
    academic_year: Optional[str],
    round_val: Optional[str],
    status_val: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
) -> Tuple[str, str]:
    """Helper to dispatch to the appropriate report generator."""
    rtype = report_type.lower().strip()

    if rtype in ["enrolment", "enrollment"]:
        csv_data = generate_enrolment_report_csv(
            db=db,
            user=user,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
            round_val=round_val,
            status_val=status_val,
            from_date=from_date,
            to_date=to_date,
        )
        filename_prefix = "enrolment_ledger_report"
    elif rtype == "compliance":
        csv_data = generate_compliance_report_csv(
            db=db,
            user=user,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
            round_val=round_val,
            status_val=status_val,
            from_date=from_date,
            to_date=to_date,
        )
        filename_prefix = "seat_compliance_report"
    elif rtype == "data-quality":
        csv_data = generate_data_quality_report_csv(
            db=db,
            user=user,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
            round_val=round_val,
            status_val=status_val,
            from_date=from_date,
            to_date=to_date,
        )
        filename_prefix = "data_quality_report"
    elif rtype == "duplicates":
        csv_data = generate_duplicates_report_csv(
            db=db,
            user=user,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
            round_val=round_val,
            status_val=status_val,
            from_date=from_date,
            to_date=to_date,
        )
        filename_prefix = "duplicates_anomaly_report"
    elif rtype == "timeliness":
        csv_data = generate_timeliness_report_csv(
            db=db,
            user=user,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
            round_val=round_val,
            status_val=status_val,
            from_date=from_date,
            to_date=to_date,
        )
        filename_prefix = "submission_timeliness_report"
    elif rtype == "audit":
        csv_data = generate_audit_report_csv(
            db=db,
            user=user,
            institution_id=institution_id,
            programme=programme,
            academic_year=academic_year,
            round_val=round_val,
            status_val=status_val,
            from_date=from_date,
            to_date=to_date,
        )
        filename_prefix = "immutable_audit_trail_report"
    else:
        raise BadRequestError(
            f"Unsupported report type '{report_type}'. "
            "Supported report types: enrolment, compliance, data-quality, duplicates, timeliness, audit."
        )

    return csv_data, filename_prefix


# Tuple import
from typing import Tuple


@router.get("/compliance", summary="Generate Statutory Seat Allocation & Quota Compliance Report")
def export_compliance_report(
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Admission status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type="compliance",
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )


@router.get("/enrolment", summary="Generate Statutory Student Enrolment Ledger Report")
@router.get("/enrollment", summary="Generate Statutory Student Enrollment Ledger Report (alias)")
def export_enrolment_report(
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Admission status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type="enrolment",
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )


@router.get("/data-quality", summary="Generate Data Quality Score & Ingestion Hygiene Report")
def export_data_quality_report(
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Admission status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type="data-quality",
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )


@router.get("/duplicates", summary="Generate Duplicate Candidates & Anomaly Cases Report")
def export_duplicates_report(
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Case status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type="duplicates",
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )


@router.get("/timeliness", summary="Generate Submission Timeliness & Calendar Deadlines Report")
def export_timeliness_report(
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Submission status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type="timeliness",
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )


@router.get("/audit", summary="Generate Statutory Immutable Audit Trail Report")
def export_audit_report(
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type="audit",
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )


@router.get("/{report_type}", summary="Generate Report by Dynamic Parameter Name")
def export_generic_report(
    report_type: str,
    institution: Optional[str] = Query(None, description="Institution ID filter"),
    institution_id: Optional[str] = Query(None, description="Alias for institution ID"),
    programme: Optional[str] = Query(None, description="Academic programme filter"),
    program_id: Optional[str] = Query(None, description="Alias for academic programme filter"),
    year: Optional[str] = Query(None, description="Academic year filter"),
    academic_year: Optional[str] = Query(None, description="Alias for academic year filter"),
    round: Optional[str] = Query(None, description="Admission round filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    from_date: Optional[str] = Query(None, description="Start date ISO string"),
    to_date: Optional[str] = Query(None, description="End date ISO string"),
    format: Optional[str] = Query("csv", description="Output format"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    inst = institution or institution_id
    prog = programme or program_id
    ay = year or academic_year
    csv_data, prefix = resolve_report_csv(
        report_type=report_type,
        db=db,
        user=user,
        institution_id=inst,
        programme=prog,
        academic_year=ay,
        round_val=round,
        status_val=status,
        from_date=from_date,
        to_date=to_date,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{prefix}_{timestamp}.csv"'},
    )
