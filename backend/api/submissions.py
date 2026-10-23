"""
Submission Pipeline API Endpoints (api/submissions.py).
Endpoints:
- POST /api/submissions
- POST /api/submissions/{id}/upload
- POST /api/submissions/{id}/validate (DRY RUN)
- GET /api/submissions/{id}/errors
- GET /api/submissions/{id}/rows
- POST /api/submissions/{id}/commit
- POST /api/submissions/{id}/retry
- GET /api/submissions/{id}/report
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.submission import RowOutcome, Submission, SubmissionRow
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.schemas.submission import (
    CommitSubmissionRequest,
    CreateSubmissionRequest,
    RowError,
    SubmissionResponse,
    SubmissionRowResponse,
    SubmissionRowsPage,
)
from backend.security.authz import (
    InstitutionScope,
    UserPrincipal,
    institution_scope,
    require_authenticated_user,
    require_roles,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_AUDITOR,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
)
from backend.services.submission_service import SubmissionService

submissions_router = APIRouter(prefix="/submissions", tags=["Submissions Pipeline"])


@submissions_router.post("", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
def create_submission_endpoint(
    payload: CreateSubmissionRequest,
    current_user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/submissions:
    Initializes a new admission batch submission.
    Idempotent via idempotency_key.
    Enforces institution scoping (Rule 7).
    """
    target_inst = scope.validate_access(payload.institution_id or current_user.institution_id)
    if not target_inst:
        raise BadRequestError("Target institution_id is required.")

    service = SubmissionService(db)
    sub = service.create_submission(
        institution_id=target_inst,
        academic_year=payload.academic_year,
        programme=payload.programme,
        round_str=payload.round,
        uploaded_by=current_user.user_id,
        idempotency_key=payload.idempotency_key,
    )

    return SubmissionResponse(
        id=str(sub.id),
        institution_id=str(sub.institution_id),
        academic_year=sub.academic_year,
        programme=sub.programme,
        round=sub.round,
        status=sub.status,
        idempotency_key=sub.idempotency_key,
        counts=sub.counts,
        is_locked=sub.is_locked,
        lock_reason=sub.lock_reason,
        created_at=sub.created_at.isoformat(),
    )


@submissions_router.post("/{submission_id}/upload")
@submissions_router.post("/{submission_id}/upload-csv")
async def upload_csv_endpoint(
    submission_id: str,
    request: Request,
    file: Optional[UploadFile] = File(None),
    current_user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/submissions/{id}/upload:
    Uploads and parses CSV admission batch.
    Enforces 10MB size limit, UTF-8/BOM handling, formula-injection sanitization (= + - @),
    header mapping, and demographic normalization.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    # Read bytes either from multipart file or direct raw request body
    if file:
        content_bytes = await file.read()
    else:
        content_bytes = await request.body()

    if not content_bytes:
        raise BadRequestError("No CSV content provided in request.")

    service = SubmissionService(db)
    result = service.upload_csv_file(
        submission_id=submission_id,
        content_bytes=content_bytes,
        actor_id=current_user.user_id,
    )
    return result


@submissions_router.post("/{submission_id}/validate")
@submissions_router.post("/{submission_id}/validate-dry-run")
async def validate_submission_endpoint(
    submission_id: str,
    current_user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/submissions/{id}/validate (DRY RUN):
    Executes dry run validation across all rows.
    Writes NOTHING except validation results; reserves no seats.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    service = SubmissionService(db)
    result = await service.validate_submission_dry_run(
        submission_id=submission_id,
        actor_id=current_user.user_id,
    )
    return result


@submissions_router.get("/{submission_id}/errors", response_model=List[RowError])
def get_submission_errors_endpoint(
    submission_id: str,
    current_user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/submissions/{id}/errors:
    Returns per-row errors: row_number, field, error_code, explanation, suggested_fix.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    rows = (
        db.query(SubmissionRow)
        .filter(SubmissionRow.submission_id == sub.id)
        .order_by(SubmissionRow.row_number.asc())
        .all()
    )

    flat_errors: List[RowError] = []
    for r in rows:
        if r.errors:
            for err in r.errors:
                flat_errors.append(
                    RowError(
                        row_number=r.row_number,
                        field=err.get("field", "unknown"),
                        error_code=err.get("error_code", "VALIDATION_ERROR"),
                        explanation=err.get("explanation", ""),
                        suggested_fix=err.get("suggested_fix", ""),
                    )
                )

    return flat_errors


@submissions_router.get("/{submission_id}/rows", response_model=SubmissionRowsPage)
def get_submission_rows_endpoint(
    submission_id: str,
    outcome: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/submissions/{id}/rows:
    Returns paginated submission rows with optional outcome filter.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    query = db.query(SubmissionRow).filter(SubmissionRow.submission_id == sub.id)
    if outcome:
        query = query.filter(SubmissionRow.outcome == outcome.upper())

    total = query.count()
    rows = query.order_by(SubmissionRow.row_number.asc()).offset((page - 1) * page_size).limit(page_size).all()

    return SubmissionRowsPage(
        total=total,
        page=page,
        page_size=page_size,
        rows=[
            SubmissionRowResponse(
                id=str(r.id),
                submission_id=str(r.submission_id),
                row_number=r.row_number,
                raw=r.raw,
                normalized=r.normalized,
                outcome=r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome),
                errors=r.errors,
                row_key=r.row_key,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ],
    )


@submissions_router.post("/{submission_id}/commit")
async def commit_submission_endpoint(
    submission_id: str,
    payload: Optional[CommitSubmissionRequest] = None,
    current_user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/submissions/{id}/commit:
    Commits admission records using CURRENT frozen approval.
    Per row, ONE database transaction with row-level locking (SELECT ... FOR UPDATE).
    Two concurrent commits for the last seat: exactly one succeeds.
    Reports COMMITTED / FAILED / UNPROCESSED.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    service = SubmissionService(db)
    reason = payload.reason_code if payload else None
    explanation = payload.explanation if payload else None

    result = await service.commit_submission(
        submission_id=submission_id,
        actor_id=current_user.user_id,
        reason_code=reason,
        explanation=explanation,
    )
    return result


@submissions_router.post("/{submission_id}/retry")
async def retry_submission_endpoint(
    submission_id: str,
    current_user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/submissions/{id}/retry:
    Idempotent retry for FAILED or UNPROCESSED rows.
    Retrying never double-inserts due to unique row_key.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    service = SubmissionService(db)
    result = await service.retry_submission(
        submission_id=submission_id,
        actor_id=current_user.user_id,
    )
    return result


@submissions_router.get("/{submission_id}/report")
def get_submission_report_endpoint(
    submission_id: str,
    current_user: UserPrincipal = Depends(require_authenticated_user),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    GET /api/submissions/{id}/report:
    Downloads results as a CSV file.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise NotFoundError(f"Submission '{submission_id}' not found.")

    scope.validate_access(sub.institution_id)

    service = SubmissionService(db)
    csv_data = service.generate_results_csv(submission_id)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=submission_{submission_id[:8]}_report.csv"
        },
    )
