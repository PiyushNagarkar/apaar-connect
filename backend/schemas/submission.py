from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CreateSubmissionRequest(BaseModel):
    institution_id: Optional[str] = None
    academic_year: str
    programme: str
    round: str = "ROUND_1"
    idempotency_key: Optional[str] = None


class CommitSubmissionRequest(BaseModel):
    reason_code: Optional[str] = None
    explanation: Optional[str] = None


class RowError(BaseModel):
    row_number: int
    field: str
    error_code: str
    explanation: str
    suggested_fix: str


class SubmissionResponse(BaseModel):
    id: str
    institution_id: str
    academic_year: Optional[str] = None
    programme: Optional[str] = None
    round: str
    status: str
    idempotency_key: Optional[str] = None
    counts: Optional[Dict[str, Any]] = None
    is_locked: bool = False
    lock_reason: Optional[str] = None
    created_at: str


class SubmissionRowResponse(BaseModel):
    id: str
    submission_id: str
    row_number: int
    raw: Dict[str, Any]
    normalized: Optional[Dict[str, Any]] = None
    outcome: str
    errors: Optional[List[Dict[str, Any]]] = None
    row_key: str
    created_at: str


class SubmissionRowsPage(BaseModel):
    total: int
    page: int
    page_size: int
    rows: List[SubmissionRowResponse]


class SingleStudentAdmissionRequest(BaseModel):
    institution_id: Optional[str] = None
    apaar_id: Optional[str] = None
    name: str
    dob: str  # YYYY-MM-DD
    gender: str
    mobile: Optional[str] = None
    email: Optional[str] = None
    roll_no: Optional[str] = None
    programme: str
    branch: str
    campus: str = "MAIN"
    shift: str = "FIRST"
    academic_year: str
    seat_type: str = "REGULAR"
    category: str = "OPEN"
    nri_flag: bool = False
    oci_flag: bool = False
    fn_flag: bool = False
    admission_date: str
    consent_reference: Optional[str] = None
    evidence_ref: Optional[str] = None
    round: str = "ROUND_1"
    reason_code: Optional[str] = None
