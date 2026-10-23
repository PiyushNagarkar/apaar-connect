from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.student import Student
from backend.schemas.errors import BadRequestError, ForbiddenError, NotFoundError
from backend.schemas.submission import SingleStudentAdmissionRequest
from backend.security.authz import (
    InstitutionScope,
    UserPrincipal,
    institution_scope,
    require_authenticated_user,
    require_roles,
)
from backend.security.masking import mask_student_for_role
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
)
from backend.services.submission_service import create_single_student_admission

router = APIRouter(prefix="/students", tags=["Students"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_student_admission_endpoint(
    payload: SingleStudentAdmissionRequest,
    current_user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR)),
    scope: InstitutionScope = Depends(institution_scope),
    db: Session = Depends(get_db),
):
    """
    POST /api/students:
    Single-record entry using the exact same code path:
    - Demographic normalization
    - Cross-field rules (NRI/OCI/FN vs seat_type)
    - Row-level lock on SeatAllocation (with_for_update)
    - Capacity check on frozen approval
    - Identity verification
    - RecordVersion snapshot and AuditEvent
    """
    target_inst = scope.validate_access(payload.institution_id or current_user.institution_id)
    if not target_inst:
        raise BadRequestError("Target institution_id is required.")

    result = await create_single_student_admission(
        db=db,
        payload=payload.model_dump(),
        actor_id=current_user.user_id,
        institution_id=target_inst,
    )
    return result


@router.get("/{student_id}")
def get_student(
    student_id: str,
    current_user: UserPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """
    GET /api/students/{student_id}:
    - If caller is a STUDENT: verifies student_id matches current_user.student_id.
      Requesting another student's record raises HTTP 403 Forbidden.
    - Applies field-level privacy masking tailored to the caller's role.
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise NotFoundError(f"Student '{student_id}' was not found.")

    is_own_record = (current_user.student_id == student_id)

    # Acceptance check: student requests another student -> 403
    if current_user.role == ROLE_STUDENT and not is_own_record:
        raise ForbiddenError("Access forbidden: Students are permitted to view only their own records.")

    # Return sanitized field-level masked projection
    return mask_student_for_role(student, current_user.role, is_own_record=is_own_record)

