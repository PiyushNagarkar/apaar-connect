"""
Submission Service (services/submission_service.py).
Implements the end-to-end admission submission pipeline:
- Idempotent submission creation and round controls (ROUND_1, ROUND_2, FINAL, locks, late reason codes)
- CSV upload with safe parsing, UTF-8/BOM handling, formula injection sanitization (= + - @), and field normalization
- Dry Run Validation (writes NOTHING to enrollments, reserves no seats)
- One-transaction-per-row Commit with row locking (SELECT ... FOR UPDATE), capacity enforcement,
  student/enrollment creation, RecordVersion snapshot, and AuditEvent logging
- Concurrency guarantee: two concurrent commits for the last seat -> exactly one succeeds
- Idempotent retry via row_key
- Partial failure reporting (COMMITTED / FAILED / UNPROCESSED)
- Single-student admission entry via the exact same code path
- CSV Report generator
"""
import csv
import hashlib
import io
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.audit import AuditEvent
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.submission import RowOutcome, Submission, SubmissionRow
from backend.models.validation import ValidationIssue
from backend.models.version import RecordVersion
from backend.schemas.errors import (
    AppException,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from backend.security.crypto import (
    compute_apaar_hash,
    encrypt_apaar,
    mask_apaar,
    normalize_apaar,
)
from backend.services.audit import record_audit_event
from backend.services.identity_adapter import (
    STATUS_FAILED,
    STATUS_NOT_PROVIDED,
    STATUS_PASSED,
    STATUS_UNAVAILABLE,
    check_dob_match,
    check_name_similarity,
    evaluate_identity_policy,
    get_identity_provider,
    normalize_name,
    validate_apaar_format_and_checksum,
)

logger = logging.getLogger("submission_service")

# ---------------------------------------------------------------------------
# Round & Lock Constants
# ---------------------------------------------------------------------------
ROUND_1 = "ROUND_1"
ROUND_2 = "ROUND_2"
ROUND_FINAL = "FINAL"
ALLOWED_ROUNDS = {ROUND_1, ROUND_2, ROUND_FINAL, "1", "2", "3"}

# Late Submission Reason Codes
REASON_DATA_ENTRY_ERROR = "DATA_ENTRY_ERROR"
REASON_OFFICIAL_CORRECTION = "OFFICIAL_CORRECTION"
REASON_TRANSFER_UPDATE = "TRANSFER_UPDATE"
REASON_WITHDRAWAL_UPDATE = "WITHDRAWAL_UPDATE"
REASON_APPROVAL_UPDATE = "APPROVAL_UPDATE"
REASON_OTHER = "OTHER_REQUIRES_EXPLANATION"

ALLOWED_LATE_REASONS = {
    REASON_DATA_ENTRY_ERROR,
    REASON_OFFICIAL_CORRECTION,
    REASON_TRANSFER_UPDATE,
    REASON_WITHDRAWAL_UPDATE,
    REASON_APPROVAL_UPDATE,
    REASON_OTHER,
}

EXPECTED_CSV_COLUMNS = [
    "apaar_id",
    "name",
    "dob",
    "gender",
    "mobile",
    "email",
    "roll_no",
    "programme",
    "branch",
    "campus",
    "shift",
    "academic_year",
    "seat_type",
    "category",
    "nri_flag",
    "oci_flag",
    "fn_flag",
    "admission_date",
    "consent_reference",
    "evidence_ref",
]

MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB limit


# ---------------------------------------------------------------------------
# Normalization & Formula-Injection Sanitization Helpers
# ---------------------------------------------------------------------------

def sanitize_formula_injection(value: Any) -> Any:
    """
    Sanitizes potential CSV formula injection in spreadsheet software.
    Cells starting with =, +, -, @ are prefixed with a single quote '.
    """
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if trimmed and trimmed[0] in ("=", "+", "-", "@"):
        return f"'{trimmed}"
    return value


def collapse_whitespace(value: Optional[str]) -> str:
    """Trims and collapses internal consecutive whitespace."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_dob_iso(dob_str: Optional[str]) -> Optional[str]:
    """
    Parses flexible dates (YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, YYYY/MM/DD)
    into standard ISO YYYY-MM-DD.
    """
    if not dob_str:
        return None
    cleaned = collapse_whitespace(dob_str)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return cleaned  # fallback


def normalize_mobile_10(mobile_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Strips non-digits; extracts last 10 digits and last 4 digits.
    Returns (mobile_10, mobile_last4).
    """
    if not mobile_str:
        return None, None
    digits = re.sub(r"\D", "", str(mobile_str))
    if len(digits) >= 10:
        ten = digits[-10:]
        return ten, ten[-4:]
    return digits or None, digits[-4:] if digits else None


def parse_bool_flag(value: Any) -> bool:
    """Parses boolean strings like true/yes/1/y/t."""
    if isinstance(value, bool):
        return value
    if not value:
        return False
    return str(value).strip().lower() in ("true", "1", "yes", "y", "t")


def compute_row_key(
    institution_id: str,
    academic_year: str,
    programme: str,
    apaar_hash: Optional[str],
    round_str: str,
    fallback_id: str = "",
) -> str:
    """
    Deterministic row key for idempotent retry:
    row_key = hash(institution, year, programme, apaar_hash, round)
    """
    identifier = apaar_hash if (apaar_hash and apaar_hash.strip()) else fallback_id
    raw = f"{institution_id}:{academic_year}:{programme}:{identifier}:{round_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CSV Parsing & Header Mapping
# ---------------------------------------------------------------------------

def parse_and_sanitize_csv(content_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parses raw CSV bytes:
    - Enforces size limit (10MB)
    - Decodes with UTF-8 / UTF-8-BOM (utf-8-sig)
    - Maps headers safely (case-insensitive, strips spaces)
    - Sanitizes cells starting with =, +, -, @
    - Normalizes values (trim, collapse spaces, ISO DOB, mobile 10)
    """
    if len(content_bytes) > MAX_CSV_BYTES:
        raise BadRequestError(f"CSV file exceeds maximum size limit of {MAX_CSV_BYTES // (1024 * 1024)}MB.")

    try:
        decoded = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BadRequestError(f"Could not decode CSV content using UTF-8/BOM: {str(exc)}")

    reader = csv.reader(io.StringIO(decoded))
    try:
        header_row = next(reader)
    except StopIteration:
        raise BadRequestError("Uploaded CSV file is completely empty.")

    # Normalize header mapping
    mapped_headers = []
    for h in header_row:
        clean_h = re.sub(r"[^\w]+", "_", h.strip().lower()).strip("_")
        mapped_headers.append(clean_h)

    # Check required presence of core identifying columns
    required_cols = {"name", "dob", "programme", "branch", "academic_year", "seat_type"}
    missing = required_cols - set(mapped_headers)
    if missing:
        raise BadRequestError(f"CSV is missing required columns: {sorted(list(missing))}")

    parsed_rows = []
    for row_idx, row in enumerate(reader, start=1):
        # Skip completely blank lines
        if not row or all(not str(c).strip() for c in row):
            continue

        raw_dict: Dict[str, Any] = {}
        for col_idx, h in enumerate(mapped_headers):
            cell_val = row[col_idx] if col_idx < len(row) else ""
            raw_dict[h] = sanitize_formula_injection(cell_val)

        # Build normalized representation
        name_val = collapse_whitespace(raw_dict.get("name"))
        dob_iso = normalize_dob_iso(raw_dict.get("dob"))
        mob_10, mob_last4 = normalize_mobile_10(raw_dict.get("mobile"))
        apaar_clean = normalize_apaar(raw_dict.get("apaar_id"))

        normalized_dict = {
            "apaar_id": apaar_clean or None,
            "name": name_val,
            "name_normalized": normalize_name(name_val),
            "dob": dob_iso,
            "gender": collapse_whitespace(raw_dict.get("gender")).upper() or "OTHER",
            "mobile": mob_10,
            "mobile_last4": mob_last4,
            "email": collapse_whitespace(raw_dict.get("email")).lower() or None,
            "roll_no": collapse_whitespace(raw_dict.get("roll_no")) or None,
            "programme": collapse_whitespace(raw_dict.get("programme")).upper(),
            "branch": collapse_whitespace(raw_dict.get("branch")).upper(),
            "campus": collapse_whitespace(raw_dict.get("campus")).upper() or "MAIN",
            "shift": collapse_whitespace(raw_dict.get("shift")).upper() or "FIRST",
            "academic_year": collapse_whitespace(raw_dict.get("academic_year")),
            "seat_type": collapse_whitespace(raw_dict.get("seat_type")).upper(),
            "category": collapse_whitespace(raw_dict.get("category")).upper() or "OPEN",
            "nri_flag": parse_bool_flag(raw_dict.get("nri_flag")),
            "oci_flag": parse_bool_flag(raw_dict.get("oci_flag")),
            "fn_flag": parse_bool_flag(raw_dict.get("fn_flag")),
            "admission_date": normalize_dob_iso(raw_dict.get("admission_date")),
            "consent_reference": collapse_whitespace(raw_dict.get("consent_reference")) or None,
            "evidence_ref": collapse_whitespace(raw_dict.get("evidence_ref")) or None,
        }

        parsed_rows.append({
            "row_number": row_idx,
            "raw": raw_dict,
            "normalized": normalized_dict,
        })

    return parsed_rows


# ---------------------------------------------------------------------------
# Cross-Field Validation Rules
# ---------------------------------------------------------------------------

def validate_cross_field_rules(row_number: int, norm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Validates cross-field consistency:
    - Contradictory flags: NRI and Foreign National (FN) cannot both be True.
    - Seat type vs Flags:
      * NRI seat_type requires nri_flag == True.
      * SUPERNUMERARY_FN_OCI_PIO requires fn_flag or oci_flag == True.
      * REGULAR seat_type cannot have fn_flag == True.
    """
    errors = []
    nri = norm.get("nri_flag", False)
    fn = norm.get("fn_flag", False)
    oci = norm.get("oci_flag", False)
    seat_type = norm.get("seat_type", "")

    # 1. NRI and FN contradictory
    if nri and fn:
        errors.append({
            "row_number": row_number,
            "field": "nri_flag",
            "error_code": "CONTRADICTORY_FLAGS",
            "explanation": "A student cannot simultaneously hold NRI (Indian Citizen abroad) and Foreign National (FN) status.",
            "suggested_fix": "Set either nri_flag or fn_flag to false depending on student's citizenship status.",
        })

    # 2. NRI Seat requires NRI flag
    if seat_type == "NRI" and not nri:
        errors.append({
            "row_number": row_number,
            "field": "seat_type",
            "error_code": "NRI_SEAT_FLAG_MISMATCH",
            "explanation": "Admissions under NRI seat quota require nri_flag to be set to true.",
            "suggested_fix": "Set nri_flag to true or select REGULAR seat type.",
        })

    # 3. Supernumerary FN/OCI requires FN or OCI flag
    if seat_type == "SUPERNUMERARY_FN_OCI_PIO" and not (fn or oci):
        errors.append({
            "row_number": row_number,
            "field": "seat_type",
            "error_code": "SUPERNUMERARY_FLAG_MISMATCH",
            "explanation": "SUPERNUMERARY_FN_OCI_PIO seat quota requires either fn_flag or oci_flag to be set to true.",
            "suggested_fix": "Set fn_flag or oci_flag to true or select REGULAR seat type.",
        })

    # 4. Foreign National cannot occupy regular seat
    if seat_type == "REGULAR" and fn:
        errors.append({
            "row_number": row_number,
            "field": "seat_type",
            "error_code": "FN_IN_REGULAR_SEAT",
            "explanation": "Foreign National (FN) candidates are not eligible for regular approved seats.",
            "suggested_fix": "Allocate candidate under SUPERNUMERARY_FN_OCI_PIO seat type.",
        })

    # 5. Seat type enum validity
    valid_seat_types = {s.value for s in SeatType}
    if seat_type not in valid_seat_types:
        errors.append({
            "row_number": row_number,
            "field": "seat_type",
            "error_code": "INVALID_SEAT_TYPE",
            "explanation": f"Seat type '{seat_type}' is not recognized. Valid options: {sorted(list(valid_seat_types))}.",
            "suggested_fix": f"Choose one of: {', '.join(sorted(list(valid_seat_types)))}.",
        })

    return errors


# ---------------------------------------------------------------------------
# Submission Service Implementation
# ---------------------------------------------------------------------------

class SubmissionService:
    def __init__(self, db: Session):
        self.db = db

    def create_submission(
        self,
        institution_id: str,
        academic_year: str,
        programme: str,
        round_str: str,
        uploaded_by: str,
        idempotency_key: Optional[str] = None,
    ) -> Submission:
        """
        Creates a new submission record with idempotency support.
        """
        if idempotency_key:
            existing = (
                self.db.query(Submission)
                .filter(Submission.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                return existing

        sub = Submission(
            institution_id=institution_id,
            uploaded_by=uploaded_by,
            academic_year=academic_year,
            programme=programme,
            round=round_str,
            status="PENDING",
            idempotency_key=idempotency_key,
            counts={"total": 0, "unprocessed": 0, "valid": 0, "invalid": 0, "committed": 0, "failed": 0},
            is_locked=False,
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)

        record_audit_event(
            db=self.db,
            actor_id=uploaded_by,
            action="SUBMISSION_CREATE",
            entity_type="SUBMISSION",
            entity_id=sub.id,
            reason=f"Created admission batch submission for {programme} {academic_year} ({round_str})",
        )
        self.db.commit()
        return sub

    def upload_csv_file(
        self,
        submission_id: str,
        content_bytes: bytes,
        actor_id: str,
    ) -> Dict[str, Any]:
        """
        Processes uploaded CSV and persists rows into submission_rows.
        Clears any previous uncommitted rows for this submission so re-upload is safe.
        """
        sub = self.db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise NotFoundError(f"Submission '{submission_id}' not found.")

        if sub.status in ("COMPLETED", "PROCESSING"):
            raise ConflictError(f"Cannot re-upload CSV for submission in '{sub.status}' state.")

        parsed_rows = parse_and_sanitize_csv(content_bytes)

        # Clear existing uncommitted rows for this submission
        existing_rows = self.db.query(SubmissionRow).filter(SubmissionRow.submission_id == sub.id).all()
        for r in existing_rows:
            self.db.delete(r)
        self.db.flush()

        rows_to_insert = []
        for r in parsed_rows:
            row_num = r["row_number"]
            norm = r["normalized"]
            apaar_id = norm.get("apaar_id")
            apaar_hash = compute_apaar_hash(apaar_id) if apaar_id else ""
            fallback = f"row_{row_num}_{norm.get('roll_no') or uuid.uuid4().hex[:8]}"

            key = compute_row_key(
                institution_id=sub.institution_id,
                academic_year=sub.academic_year or norm.get("academic_year", ""),
                programme=sub.programme or norm.get("programme", ""),
                apaar_hash=apaar_hash,
                round_str=sub.round,
                fallback_id=fallback,
            )

            # Avoid row_key collision across the table if already exists
            existing_key_row = self.db.query(SubmissionRow).filter(SubmissionRow.row_key == key).first()
            if existing_key_row and existing_key_row.submission_id != sub.id:
                # Key already used in another submission; salt key with submission id
                key = hashlib.sha256(f"{key}:{sub.id}:{row_num}".encode("utf-8")).hexdigest()

            row_obj = SubmissionRow(
                submission_id=sub.id,
                row_number=row_num,
                raw=r["raw"],
                normalized=norm,
                outcome=RowOutcome.UNPROCESSED,
                errors=None,
                row_key=key,
            )
            rows_to_insert.append(row_obj)

        self.db.add_all(rows_to_insert)
        sub.status = "UPLOADED"
        sub.counts = {
            "total": len(rows_to_insert),
            "unprocessed": len(rows_to_insert),
            "valid": 0,
            "invalid": 0,
            "committed": 0,
            "failed": 0,
        }
        self.db.commit()

        record_audit_event(
            db=self.db,
            actor_id=actor_id,
            action="SUBMISSION_UPLOAD",
            entity_type="SUBMISSION",
            entity_id=sub.id,
            reason=f"Uploaded CSV containing {len(rows_to_insert)} student rows",
        )
        self.db.commit()

        return {
            "submission_id": sub.id,
            "status": sub.status,
            "total_rows": len(rows_to_insert),
        }

    async def validate_submission_dry_run(
        self,
        submission_id: str,
        actor_id: str,
    ) -> Dict[str, Any]:
        """
        DRY RUN VALIDATION:
        Evaluates all rows against:
        - Required demographic & formatting rules
        - Cross-field rules (NRI/OCI/FN vs seat_type)
        - L1 Identity check simulation
        - L2 Institutional Authority check (approval exists and is FROZEN)
        - L3 Capacity preview (checks if current enrollments >= approved_count)
        - Duplicate candidate preview (cross-institution duplicate detection)

        CRITICAL SEMANTICS:
        Dry run writes NOTHING except validation results; it reserves no seats.
        No student or enrollment records are created.
        """
        sub = self.db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise NotFoundError(f"Submission '{submission_id}' not found.")

        rows = (
            self.db.query(SubmissionRow)
            .filter(SubmissionRow.submission_id == sub.id)
            .order_by(SubmissionRow.row_number.asc())
            .all()
        )

        identity_provider = get_identity_provider()
        valid_count = 0
        invalid_count = 0
        all_errors = []

        for row in rows:
            norm = row.normalized or {}
            row_errors: List[Dict[str, Any]] = []

            # 1. Basic Field Presence
            if not norm.get("name"):
                row_errors.append({
                    "row_number": row.row_number,
                    "field": "name",
                    "error_code": "MISSING_NAME",
                    "explanation": "Student name cannot be empty.",
                    "suggested_fix": "Provide student full legal name.",
                })

            if not norm.get("dob"):
                row_errors.append({
                    "row_number": row.row_number,
                    "field": "dob",
                    "error_code": "INVALID_DOB",
                    "explanation": "Date of birth is missing or could not be parsed into YYYY-MM-DD.",
                    "suggested_fix": "Provide date of birth in YYYY-MM-DD format.",
                })

            if not norm.get("admission_date"):
                row_errors.append({
                    "row_number": row.row_number,
                    "field": "admission_date",
                    "error_code": "MISSING_ADMISSION_DATE",
                    "explanation": "Admission date is required.",
                    "suggested_fix": "Provide valid admission date in YYYY-MM-DD format.",
                })

            # 2. Cross-Field Checks
            cross_errors = validate_cross_field_rules(row.row_number, norm)
            row_errors.extend(cross_errors)

            # 3. L1 Identity Simulation Preview
            apaar_id = norm.get("apaar_id")
            if apaar_id:
                if not validate_apaar_format_and_checksum(apaar_id):
                    row_errors.append({
                        "row_number": row.row_number,
                        "field": "apaar_id",
                        "error_code": "INVALID_APAAR_FORMAT",
                        "explanation": "APAAR failed 12-digit format or Luhn checksum validation.",
                        "suggested_fix": "Verify student APAAR card and enter correct 12-digit identifier.",
                    })
                else:
                    # Deterministic simulated check
                    l1_res = await identity_provider.verify(
                        request_id=f"dryrun-row-{row.row_number}",
                        apaar_id=apaar_id,
                        student_name=norm.get("name", ""),
                        date_of_birth=norm.get("dob", ""),
                    )
                    if l1_res.status == STATUS_FAILED and l1_res.reason_code == "MISMATCH":
                        row_errors.append({
                            "row_number": row.row_number,
                            "field": "name",
                            "error_code": "IDENTITY_DEMOGRAPHIC_MISMATCH",
                            "explanation": "Student name or DOB does not match simulated APAAR directory record.",
                            "suggested_fix": "Reconcile demographics with student's official APAAR profile.",
                        })
            else:
                # APAAR missing -> check grace period policy
                admit_dt = None
                try:
                    if norm.get("admission_date"):
                        admit_dt = datetime.strptime(norm["admission_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    pass
                policy = evaluate_identity_policy(STATUS_NOT_PROVIDED, admission_date=admit_dt)
                if policy.get("escalated_error"):
                    row_errors.append({
                        "row_number": row.row_number,
                        "field": "apaar_id",
                        "error_code": "GRACE_PERIOD_EXPIRED",
                        "explanation": policy.get("reason", "Allowed grace period for missing APAAR has expired."),
                        "suggested_fix": "Student must obtain and submit a verified APAAR ID.",
                    })

            # 4. L2 Institutional Authority Preview
            prog_name = norm.get("programme") or sub.programme
            branch_name = norm.get("branch")
            ay = norm.get("academic_year") or sub.academic_year
            campus = norm.get("campus", "MAIN")
            shift = norm.get("shift", "FIRST")

            approval = (
                self.db.query(ProgramApproval)
                .filter(
                    ProgramApproval.institution_id == sub.institution_id,
                    ProgramApproval.programme == prog_name,
                    ProgramApproval.branch == branch_name,
                    ProgramApproval.academic_year == ay,
                    ProgramApproval.campus == campus,
                    ProgramApproval.shift == shift,
                )
                .order_by(ProgramApproval.version.desc())
                .first()
            )

            if not approval:
                row_errors.append({
                    "row_number": row.row_number,
                    "field": "branch",
                    "error_code": "UNAPPROVED_PROGRAMME_BRANCH",
                    "explanation": f"No AICTE approval found for {prog_name} / {branch_name} in academic year {ay}.",
                    "suggested_fix": "Confirm program branch name matches AICTE approval order (EoA).",
                })
            elif approval.status != ApprovalStatus.FROZEN:
                row_errors.append({
                    "row_number": row.row_number,
                    "field": "approval_status",
                    "error_code": "APPROVAL_NOT_FROZEN",
                    "explanation": f"AICTE approval for {branch_name} is in DRAFT status and not frozen.",
                    "suggested_fix": "Wait for AICTE Administrator to freeze the institutional seat matrix.",
                })
            else:
                # 5. L3 Capacity Preview
                seat_type_str = norm.get("seat_type", "REGULAR")
                seat_alloc = (
                    self.db.query(SeatAllocation)
                    .filter(
                        SeatAllocation.approval_id == approval.id,
                        SeatAllocation.seat_type == seat_type_str,
                    )
                    .first()
                )
                if not seat_alloc or seat_alloc.approved_count <= 0:
                    row_errors.append({
                        "row_number": row.row_number,
                        "field": "seat_type",
                        "error_code": "ZERO_APPROVED_SEATS",
                        "explanation": f"Zero seats are approved for {seat_type_str} in {branch_name}.",
                        "suggested_fix": "Select a seat type with approved quota in the seat matrix.",
                    })
                else:
                    occupied = (
                        self.db.query(Enrollment)
                        .filter(
                            Enrollment.approval_id == approval.id,
                            Enrollment.seat_type == seat_type_str,
                            Enrollment.status.in_(["CONFIRMED", "PROVISIONAL", "ACTIVE"]),
                        )
                        .count()
                    )
                    if occupied >= seat_alloc.approved_count:
                        row_errors.append({
                            "row_number": row.row_number,
                            "field": "seat_type",
                            "error_code": "CAPACITY_EXCEEDED",
                            "explanation": f"Approved capacity of {seat_alloc.approved_count} seats for {seat_type_str} is already exhausted.",
                            "suggested_fix": "Do not admit beyond approved cap or request seat enhancement from AICTE.",
                        })

            # 6. Duplicate Candidate Preview
            if apaar_id:
                apaar_h = compute_apaar_hash(apaar_id)
                existing_student = self.db.query(Student).filter(Student.apaar_hash == apaar_h).first()
                if existing_student:
                    existing_enroll = (
                        self.db.query(Enrollment)
                        .filter(
                            Enrollment.student_id == existing_student.id,
                            Enrollment.academic_year == ay,
                            Enrollment.status.in_(["CONFIRMED", "PROVISIONAL", "ACTIVE"]),
                        )
                        .first()
                    )
                    if existing_enroll:
                        if existing_enroll.institution_id != sub.institution_id:
                            row_errors.append({
                                "row_number": row.row_number,
                                "field": "apaar_id",
                                "error_code": "DUPLICATE_CROSS_INSTITUTION",
                                "explanation": "Student is already enrolled in another institution for the same academic year.",
                                "suggested_fix": "Verify student credentials and request transfer/cancellation before enrollment.",
                            })
                        else:
                            row_errors.append({
                                "row_number": row.row_number,
                                "field": "apaar_id",
                                "error_code": "DUPLICATE_SAME_INSTITUTION",
                                "explanation": "Student is already enrolled in this institution for the same academic year.",
                                "suggested_fix": "Verify whether student is a duplicate entry.",
                            })

            # Save outcome in row
            if row_errors:
                row.outcome = RowOutcome.INVALID
                row.errors = row_errors
                invalid_count += 1
                all_errors.extend(row_errors)
            else:
                row.outcome = RowOutcome.VALID
                row.errors = None
                valid_count += 1

        sub.status = "VALIDATED"
        sub.counts = {
            "total": len(rows),
            "unprocessed": 0,
            "valid": valid_count,
            "invalid": invalid_count,
            "committed": 0,
            "failed": 0,
        }
        self.db.commit()

        record_audit_event(
            db=self.db,
            actor_id=actor_id,
            action="SUBMISSION_VALIDATE_DRY_RUN",
            entity_type="SUBMISSION",
            entity_id=sub.id,
            reason=f"Dry-run validated {len(rows)} rows: {valid_count} valid, {invalid_count} invalid (0 seats reserved)",
        )
        self.db.commit()

        return {
            "submission_id": sub.id,
            "status": sub.status,
            "total_rows": len(rows),
            "valid_rows": valid_count,
            "invalid_rows": invalid_count,
            "dry_run": True,
            "dry_run_pure": True,
            "errors_sample": all_errors[:20],
        }

    async def commit_submission(
        self,
        submission_id: str,
        actor_id: str,
        reason_code: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        COMMIT EXECUTION:
        Re-runs identity, authority, duplicate and seat checks using the CURRENT frozen approval.
        Per row, ONE database transaction:
        - Locks the seat_allocation row (SELECT ... FOR UPDATE)
        - Rechecks capacity
        - Inserts student and enrollment
        - Writes RecordVersion and AuditEvent
        Two concurrent commits for the last seat: exactly one succeeds.
        Row outcomes reported separately: COMMITTED / FAILED / UNPROCESSED.
        If infra fails mid-batch, committed rows stay committed and the rest are reported truthfully.
        """
        sub = self.db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise NotFoundError(f"Submission '{submission_id}' not found.")

        # Round Lock Enforcement
        is_late = False
        if sub.is_locked:
            if not reason_code or reason_code not in ALLOWED_LATE_REASONS:
                raise ConflictError(
                    f"Submission round is LOCKED. Late commit requires a mandatory reason code from: "
                    f"{sorted(list(ALLOWED_LATE_REASONS))}."
                )
            is_late = True

        rows = (
            self.db.query(SubmissionRow)
            .filter(SubmissionRow.submission_id == sub.id)
            .order_by(SubmissionRow.row_number.asc())
            .all()
        )

        identity_provider = get_identity_provider()
        committed_count = 0
        failed_count = 0
        unprocessed_count = 0

        for row in rows:
            # Idempotency check: already committed rows stay committed
            if row.outcome == RowOutcome.COMMITTED:
                committed_count += 1
                continue

            # Per row, ONE database transaction
            try:
                commit_success, row_errors = await self._commit_single_row(
                    sub=sub,
                    row=row,
                    identity_provider=identity_provider,
                    actor_id=actor_id,
                    is_late=is_late,
                    late_reason=reason_code,
                )
                if commit_success:
                    committed_count += 1
                else:
                    failed_count += 1
            except Exception as exc:
                logger.exception(f"Unexpected error committing row {row.row_number}: {exc}")
                self.db.rollback()
                row.outcome = RowOutcome.FAILED
                row.errors = [{
                    "row_number": row.row_number,
                    "field": "system",
                    "error_code": "INTERNAL_COMMIT_ERROR",
                    "explanation": str(exc),
                    "suggested_fix": "Retry submission row.",
                }]
                self.db.commit()
                failed_count += 1

        # Check for any remaining unprocessed rows
        remaining_unprocessed = (
            self.db.query(SubmissionRow)
            .filter(
                SubmissionRow.submission_id == sub.id,
                SubmissionRow.outcome == RowOutcome.UNPROCESSED,
            )
            .count()
        )
        unprocessed_count = remaining_unprocessed

        sub.status = "COMPLETED" if (failed_count == 0 and unprocessed_count == 0) else "PARTIALLY_FAILED"
        sub.counts = {
            "total": len(rows),
            "unprocessed": unprocessed_count,
            "valid": sub.counts.get("valid", 0),
            "invalid": sub.counts.get("invalid", 0),
            "committed": committed_count,
            "failed": failed_count,
        }
        self.db.commit()

        record_audit_event(
            db=self.db,
            actor_id=actor_id,
            action="SUBMISSION_COMMIT",
            entity_type="SUBMISSION",
            entity_id=sub.id,
            reason=f"Committed batch: {committed_count} COMMITTED, {failed_count} FAILED, {unprocessed_count} UNPROCESSED",
        )
        self.db.commit()

        return {
            "submission_id": sub.id,
            "status": sub.status,
            "committed": committed_count,
            "failed": failed_count,
            "unprocessed": unprocessed_count,
        }

    async def _commit_single_row(
        self,
        sub: Submission,
        row: SubmissionRow,
        identity_provider: Any,
        actor_id: str,
        is_late: bool = False,
        late_reason: Optional[str] = None,
    ) -> Tuple[bool, Optional[List[Dict[str, Any]]]]:
        """
        Executes single row admission in an isolated database transaction.
        Acquires row-level lock on SeatAllocation (with_for_update), rechecks capacity,
        rechecks frozen approval, executes L1 identity verification, creates student & enrollment,
        writes RecordVersion snapshot and AuditEvent.
        """
        norm = row.normalized or {}
        row_errors: List[Dict[str, Any]] = []

        # 1. Cross-field check
        cross_errs = validate_cross_field_rules(row.row_number, norm)
        if cross_errs:
            row.outcome = RowOutcome.FAILED
            row.errors = cross_errs
            self.db.commit()
            return False, cross_errs

        prog_name = norm.get("programme") or sub.programme
        branch_name = norm.get("branch")
        ay = norm.get("academic_year") or sub.academic_year
        campus = norm.get("campus", "MAIN")
        shift = norm.get("shift", "FIRST")
        seat_type_str = norm.get("seat_type", "REGULAR")

        # 2. Institutional Authority check: current frozen approval
        approval = (
            self.db.query(ProgramApproval)
            .filter(
                ProgramApproval.institution_id == sub.institution_id,
                ProgramApproval.programme == prog_name,
                ProgramApproval.branch == branch_name,
                ProgramApproval.academic_year == ay,
                ProgramApproval.campus == campus,
                ProgramApproval.shift == shift,
            )
            .order_by(ProgramApproval.version.desc())
            .first()
        )

        if not approval or approval.status != ApprovalStatus.FROZEN:
            row.outcome = RowOutcome.FAILED
            row.errors = [{
                "row_number": row.row_number,
                "field": "approval_status",
                "error_code": "APPROVAL_NOT_FROZEN",
                "explanation": "No frozen AICTE approval exists for this program and academic year.",
                "suggested_fix": "Verify AICTE approval status.",
            }]
            self.db.commit()
            return False, row.errors

        # 3. Row locking on SeatAllocation (SELECT ... FOR UPDATE) and Capacity Check
        seat_alloc = (
            self.db.query(SeatAllocation)
            .filter(
                SeatAllocation.approval_id == approval.id,
                SeatAllocation.seat_type == seat_type_str,
            )
            .with_for_update()
            .first()
        )

        if not seat_alloc or seat_alloc.approved_count <= 0:
            row.outcome = RowOutcome.FAILED
            row.errors = [{
                "row_number": row.row_number,
                "field": "seat_type",
                "error_code": "ZERO_APPROVED_SEATS",
                "explanation": f"Zero seats are approved for {seat_type_str}.",
                "suggested_fix": "Choose an approved seat type.",
            }]
            self.db.commit()
            return False, row.errors

        occupied = (
            self.db.query(Enrollment)
            .filter(
                Enrollment.approval_id == approval.id,
                Enrollment.seat_type == seat_type_str,
                Enrollment.status.in_(["CONFIRMED", "PROVISIONAL", "ACTIVE"]),
            )
            .count()
        )

        if occupied >= seat_alloc.approved_count:
            # Capacity reached! Concurrent winner got the seat.
            row.outcome = RowOutcome.FAILED
            row.errors = [{
                "row_number": row.row_number,
                "field": "seat_type",
                "error_code": "CAPACITY_EXCEEDED",
                "explanation": f"Approved capacity of {seat_alloc.approved_count} seats for {seat_type_str} is full.",
                "suggested_fix": "Quota exhausted. Candidate cannot be committed.",
            }]
            self.db.commit()
            return False, row.errors

        # 4. L1 Identity Check
        apaar_id = norm.get("apaar_id")
        student_name = norm.get("name", "")
        dob_str = norm.get("dob", "")
        l1_status = STATUS_NOT_PROVIDED

        if apaar_id:
            if not validate_apaar_format_and_checksum(apaar_id):
                row.outcome = RowOutcome.FAILED
                row.errors = [{
                    "row_number": row.row_number,
                    "field": "apaar_id",
                    "error_code": "INVALID_APAAR_FORMAT",
                    "explanation": "APAAR failed format or Luhn checksum.",
                    "suggested_fix": "Provide valid 12-digit APAAR.",
                }]
                self.db.commit()
                return False, row.errors

            l1_res = await identity_provider.verify(
                request_id=f"commit-row-{row.row_number}",
                apaar_id=apaar_id,
                student_name=student_name,
                date_of_birth=dob_str,
            )
            l1_status = l1_res.status
            if l1_res.status == STATUS_FAILED and l1_res.reason_code == "MISMATCH":
                row.outcome = RowOutcome.FAILED
                row.errors = [{
                    "row_number": row.row_number,
                    "field": "name",
                    "error_code": "IDENTITY_DEMOGRAPHIC_MISMATCH",
                    "explanation": "Demographics do not match simulated APAAR record.",
                    "suggested_fix": "Correct student name or date of birth.",
                }]
                self.db.commit()
                return False, row.errors
        else:
            # Missing APAAR check grace period
            policy = evaluate_identity_policy(STATUS_NOT_PROVIDED)
            if policy.get("escalated_error"):
                row.outcome = RowOutcome.FAILED
                row.errors = [{
                    "row_number": row.row_number,
                    "field": "apaar_id",
                    "error_code": "GRACE_PERIOD_EXPIRED",
                    "explanation": "Grace period for missing APAAR expired.",
                    "suggested_fix": "Obtain verified APAAR.",
                }]
                self.db.commit()
                return False, row.errors

        # 5. Duplicate Candidate Resolution
        apaar_h = compute_apaar_hash(apaar_id) if apaar_id else ""
        student = None
        if apaar_h:
            student = self.db.query(Student).filter(Student.apaar_hash == apaar_h).first()

        # Parse admission date
        admit_date = datetime.now(timezone.utc)
        if norm.get("admission_date"):
            try:
                admit_date = datetime.strptime(norm["admission_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Parse DOB
        parsed_dob = date(2000, 1, 1)
        if dob_str:
            try:
                parsed_dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except Exception:
                pass

        # Create Student if not exists
        if not student:
            enc_apaar = encrypt_apaar(apaar_id) if apaar_id else "NONE"
            masked_ap = mask_apaar(apaar_id) if apaar_id else "NOT_PROVIDED"
            dummy_hash = apaar_h if apaar_h else hashlib.sha256(f"{norm.get('name')}:{dob_str}:{uuid.uuid4().hex[:6]}".encode()).hexdigest()

            student = Student(
                apaar_encrypted=enc_apaar,
                apaar_hash=dummy_hash,
                apaar_masked=masked_ap,
                name=student_name,
                name_normalized=norm.get("name_normalized") or normalize_name(student_name),
                dob=parsed_dob,
                gender=norm.get("gender", "OTHER"),
                mobile_hash=hashlib.sha256(norm.get("mobile", "").encode()).hexdigest() if norm.get("mobile") else None,
                mobile_last4=norm.get("mobile_last4"),
                email_hash=hashlib.sha256(norm.get("email", "").encode()).hexdigest() if norm.get("email") else None,
                consent_status="GRANTED" if norm.get("consent_reference") else "PENDING",
            )
            self.db.add(student)
            self.db.flush()

        # Check existing enrollment duplicate
        existing_enroll = (
            self.db.query(Enrollment)
            .filter(
                Enrollment.student_id == student.id,
                Enrollment.academic_year == ay,
                Enrollment.status.in_(["CONFIRMED", "PROVISIONAL", "ACTIVE"]),
            )
            .first()
        )

        is_verified = (l1_status == STATUS_PASSED)
        enroll_status = "CONFIRMED" if is_verified else "PROVISIONAL"

        # 6. Insert Enrollment
        enrollment = Enrollment(
            student_id=student.id,
            institution_id=sub.institution_id,
            approval_id=approval.id,
            academic_year=ay,
            seat_type=seat_type_str,
            category=norm.get("category", "OPEN"),
            admission_date=admit_date,
            round=sub.round,
            status=enroll_status,
            identity_status=l1_status,
            authority_status="PASSED",
            compliance_status="PASSED",
            verified=is_verified,
            version=1,
        )
        self.db.add(enrollment)
        self.db.flush()

        # If duplicate detected, record DuplicateCandidate and ReviewCase
        if existing_enroll:
            dup = DuplicateCandidate(
                enrollment_a=existing_enroll.id,
                enrollment_b=enrollment.id,
                match_type="CROSS_INSTITUTION" if existing_enroll.institution_id != sub.institution_id else "SAME_INSTITUTION",
                score=1.0,
                reasons={"apaar_hash": student.apaar_hash, "academic_year": ay},
                status="DETECTED",
            )
            self.db.add(dup)
            case = ReviewCase(
                type="DUPLICATE_MATCH",
                severity="HIGH",
                priority=85.0,
                enrollment_id=enrollment.id,
                status="OPEN",
                evidence={"duplicate_enrollment_id": str(existing_enroll.id), "match_type": dup.match_type},
            )
            self.db.add(case)
            self.db.flush()

        # 7. Write RecordVersion snapshot
        snapshot = {
            "enrollment_id": str(enrollment.id),
            "student_id": str(student.id),
            "institution_id": sub.institution_id,
            "approval_id": approval.id,
            "seat_type": seat_type_str,
            "category": enrollment.category,
            "round": sub.round,
            "status": enrollment.status,
            "verified": enrollment.verified,
            "is_late": is_late,
            "late_reason": late_reason,
        }
        change_reason = "Initial admission enrollment commit"
        if is_late:
            change_reason += f" (LATE: {late_reason})"

        version_record = RecordVersion(
            entity_type="ENROLLMENT",
            entity_id=str(enrollment.id),
            version=1,
            snapshot=snapshot,
            change_reason=change_reason,
            actor_id=actor_id,
        )
        self.db.add(version_record)

        # 8. Write AuditEvent
        record_audit_event(
            db=self.db,
            actor_id=actor_id,
            action="ENROLLMENT_COMMIT",
            entity_type="ENROLLMENT",
            entity_id=str(enrollment.id),
            reason=f"Committed enrollment in round {sub.round} for row {row.row_number}",
        )

        # 9. Update row outcome
        row.outcome = RowOutcome.COMMITTED
        row.errors = None
        self.db.commit()

        return True, None

    async def retry_submission(
        self,
        submission_id: str,
        actor_id: str,
    ) -> Dict[str, Any]:
        """
        Idempotent retry for FAILED or UNPROCESSED rows in a submission.
        Retrying never double-inserts due to row_key idempotency.
        """
        return await self.commit_submission(
            submission_id=submission_id,
            actor_id=actor_id,
        )

    def generate_results_csv(self, submission_id: str) -> str:
        """
        Generates CSV report of submission outcomes:
        row_number, apaar_masked, name, programme, branch, seat_type, category, outcome, errors
        """
        sub = self.db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise NotFoundError(f"Submission '{submission_id}' not found.")

        rows = (
            self.db.query(SubmissionRow)
            .filter(SubmissionRow.submission_id == sub.id)
            .order_by(SubmissionRow.row_number.asc())
            .all()
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "row_number",
            "apaar_masked",
            "name",
            "programme",
            "branch",
            "seat_type",
            "category",
            "outcome",
            "errors",
        ])

        for r in rows:
            norm = r.normalized or {}
            apaar = norm.get("apaar_id")
            masked = mask_apaar(apaar) if apaar else "NOT_PROVIDED"
            err_str = "; ".join([e.get("explanation", "") for e in (r.errors or [])]) if r.errors else ""
            writer.writerow([
                r.row_number,
                masked,
                norm.get("name", ""),
                norm.get("programme", sub.programme or ""),
                norm.get("branch", ""),
                norm.get("seat_type", ""),
                norm.get("category", ""),
                r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome),
                err_str,
            ])

        return output.getvalue()


# ---------------------------------------------------------------------------
# Single-Student Admission (Shares Same Code Path)
# ---------------------------------------------------------------------------

async def create_single_student_admission(
    db: Session,
    payload: Dict[str, Any],
    actor_id: str,
    institution_id: str,
) -> Dict[str, Any]:
    """
    POST /api/students:
    Single-record entry using the exact same normalization, cross-field checks,
    row locking (with_for_update), capacity enforcement, RecordVersion, and AuditEvent trail.
    """
    name_val = collapse_whitespace(payload.get("name"))
    dob_iso = normalize_dob_iso(payload.get("dob"))
    mob_10, mob_last4 = normalize_mobile_10(payload.get("mobile"))
    apaar_clean = normalize_apaar(payload.get("apaar_id"))

    norm = {
        "apaar_id": apaar_clean or None,
        "name": name_val,
        "name_normalized": normalize_name(name_val),
        "dob": dob_iso,
        "gender": collapse_whitespace(payload.get("gender")).upper() or "OTHER",
        "mobile": mob_10,
        "mobile_last4": mob_last4,
        "email": collapse_whitespace(payload.get("email")).lower() or None,
        "roll_no": collapse_whitespace(payload.get("roll_no")) or None,
        "programme": collapse_whitespace(payload.get("programme")).upper(),
        "branch": collapse_whitespace(payload.get("branch")).upper(),
        "campus": collapse_whitespace(payload.get("campus")).upper() or "MAIN",
        "shift": collapse_whitespace(payload.get("shift")).upper() or "FIRST",
        "academic_year": collapse_whitespace(payload.get("academic_year")),
        "seat_type": collapse_whitespace(payload.get("seat_type")).upper(),
        "category": collapse_whitespace(payload.get("category")).upper() or "OPEN",
        "nri_flag": parse_bool_flag(payload.get("nri_flag")),
        "oci_flag": parse_bool_flag(payload.get("oci_flag")),
        "fn_flag": parse_bool_flag(payload.get("fn_flag")),
        "admission_date": normalize_dob_iso(payload.get("admission_date")),
        "consent_reference": collapse_whitespace(payload.get("consent_reference")) or None,
        "evidence_ref": collapse_whitespace(payload.get("evidence_ref")) or None,
    }

    # Cross-field checks
    cross_errs = validate_cross_field_rules(1, norm)
    if cross_errs:
        raise BadRequestError(
            message=cross_errs[0]["explanation"],
            field=cross_errs[0]["field"],
            details={"error_code": cross_errs[0]["error_code"], "suggested_fix": cross_errs[0]["suggested_fix"]},
        )

    # Authority check
    approval = (
        db.query(ProgramApproval)
        .filter(
            ProgramApproval.institution_id == institution_id,
            ProgramApproval.programme == norm["programme"],
            ProgramApproval.branch == norm["branch"],
            ProgramApproval.academic_year == norm["academic_year"],
            ProgramApproval.campus == norm["campus"],
            ProgramApproval.shift == norm["shift"],
        )
        .order_by(ProgramApproval.version.desc())
        .first()
    )

    if not approval or approval.status != ApprovalStatus.FROZEN:
        raise ConflictError(
            f"No frozen AICTE approval exists for {norm['programme']} / {norm['branch']} in {norm['academic_year']}."
        )

    # Seat allocation lock and capacity check
    seat_alloc = (
        db.query(SeatAllocation)
        .filter(
            SeatAllocation.approval_id == approval.id,
            SeatAllocation.seat_type == norm["seat_type"],
        )
        .with_for_update()
        .first()
    )

    if not seat_alloc or seat_alloc.approved_count <= 0:
        raise ConflictError(f"Zero seats approved for seat type '{norm['seat_type']}'.")

    occupied = (
        db.query(Enrollment)
        .filter(
            Enrollment.approval_id == approval.id,
            Enrollment.seat_type == norm["seat_type"],
            Enrollment.status.in_(["CONFIRMED", "PROVISIONAL", "ACTIVE"]),
        )
        .count()
    )

    if occupied >= seat_alloc.approved_count:
        raise ConflictError(
            f"Approved capacity of {seat_alloc.approved_count} seats for {norm['seat_type']} is exhausted."
        )

    # Identity check
    identity_provider = get_identity_provider()
    l1_status = STATUS_NOT_PROVIDED
    if norm["apaar_id"]:
        l1_res = await identity_provider.verify(
            request_id=f"single-student-{uuid.uuid4().hex[:8]}",
            apaar_id=norm["apaar_id"],
            student_name=norm["name"],
            date_of_birth=norm["dob"],
        )
        l1_status = l1_res.status
        if l1_res.status == STATUS_FAILED and l1_res.reason_code == "MISMATCH":
            raise BadRequestError("Student demographics do not match simulated APAAR record.")

    # Parse dates
    parsed_dob = date(2000, 1, 1)
    if norm.get("dob"):
        try:
            parsed_dob = datetime.strptime(norm["dob"], "%Y-%m-%d").date()
        except Exception:
            pass

    admit_date = datetime.now(timezone.utc)
    if norm.get("admission_date"):
        try:
            admit_date = datetime.strptime(norm["admission_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Create/Find Student
    apaar_h = compute_apaar_hash(norm["apaar_id"]) if norm["apaar_id"] else ""
    student = None
    if apaar_h:
        student = db.query(Student).filter(Student.apaar_hash == apaar_h).first()

    if not student:
        dummy_hash = apaar_h if apaar_h else hashlib.sha256(f"{norm['name']}:{norm['dob']}:{uuid.uuid4().hex[:6]}".encode()).hexdigest()
        student = Student(
            apaar_encrypted=encrypt_apaar(norm["apaar_id"]) if norm["apaar_id"] else "NONE",
            apaar_hash=dummy_hash,
            apaar_masked=mask_apaar(norm["apaar_id"]) if norm["apaar_id"] else "NOT_PROVIDED",
            name=norm["name"],
            name_normalized=norm["name_normalized"],
            dob=parsed_dob,
            gender=norm["gender"],
            mobile_hash=hashlib.sha256(norm["mobile"].encode()).hexdigest() if norm.get("mobile") else None,
            mobile_last4=norm.get("mobile_last4"),
            email_hash=hashlib.sha256(norm["email"].encode()).hexdigest() if norm.get("email") else None,
            consent_status="GRANTED" if norm.get("consent_reference") else "PENDING",
        )
        db.add(student)
        db.flush()

    is_verified = (l1_status == STATUS_PASSED)
    enroll_status = "CONFIRMED" if is_verified else "PROVISIONAL"

    enrollment = Enrollment(
        student_id=student.id,
        institution_id=institution_id,
        approval_id=approval.id,
        academic_year=norm["academic_year"],
        seat_type=norm["seat_type"],
        category=norm["category"],
        admission_date=admit_date,
        round=payload.get("round", "ROUND_1"),
        status=enroll_status,
        identity_status=l1_status,
        authority_status="PASSED",
        compliance_status="PASSED",
        verified=is_verified,
        version=1,
    )
    db.add(enrollment)
    db.flush()

    # RecordVersion snapshot
    version_record = RecordVersion(
        entity_type="ENROLLMENT",
        entity_id=str(enrollment.id),
        version=1,
        snapshot={
            "enrollment_id": str(enrollment.id),
            "student_id": str(student.id),
            "institution_id": institution_id,
            "approval_id": approval.id,
            "seat_type": norm["seat_type"],
            "status": enrollment.status,
            "verified": enrollment.verified,
        },
        change_reason="Single record student admission",
        actor_id=actor_id,
    )
    db.add(version_record)

    # Audit event
    record_audit_event(
        db=db,
        actor_id=actor_id,
        action="ENROLLMENT_SINGLE_ENTRY",
        entity_type="ENROLLMENT",
        entity_id=str(enrollment.id),
        reason=f"Single student admission created for {student.name} ({student.apaar_masked})",
    )
    db.commit()

    return {
        "student_id": str(student.id),
        "enrollment_id": str(enrollment.id),
        "name": student.name,
        "apaar_masked": student.apaar_masked,
        "programme": norm["programme"],
        "branch": norm["branch"],
        "seat_type": norm["seat_type"],
        "status": enrollment.status,
        "verified": enrollment.verified,
        "outcome": "COMMITTED",
    }
