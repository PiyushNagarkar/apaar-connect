"""
Validation Service and Rule Registry (services/validation_service.py).
Implements a modular rule registry for L1 Identity, L2 Authority, and L3 Seat Compliance.

Each rule returns a structured result:
{
  "rule_code": str,
  "severity": "INFO" | "WARNING" | "ERROR" | "HIGH" | "CRITICAL" | "REGULATORY_ALERT",
  "record_ref": str,
  "explanation": str,
  "recommended_action": str,
  "rule_version": str
}

Verdict Logic:
- verified = (identity PASSED and authority PASS and compliance PASS)
- Any ERROR blocks commit of that row.
- REGULATORY_ALERT and HIGH open a review case and set status to UNDER_REVIEW.
- Severity levels are configurable via the rule_severity_configs table.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.enrollment import Enrollment
from backend.models.identity import IdentityCheck
from backend.models.review import ReviewCase
from backend.models.rule_config import RuleSeverityConfig
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.validation import ValidationIssue
from backend.security.crypto import compute_apaar_hash, mask_apaar
from backend.services.identity_adapter import (
    STATUS_FAILED,
    STATUS_NOT_PROVIDED,
    STATUS_PASSED,
    STATUS_UNAVAILABLE,
    check_dob_match,
    check_name_similarity,
    evaluate_identity_policy,
    get_identity_provider,
    validate_apaar_format_and_checksum,
)
from backend.services.seat_compliance import (
    OCCUPIED_STATUSES,
    STATUS_EXCEEDED,
    calculate_approval_seat_compliance,
)

# ---------------------------------------------------------------------------
# Severity Level Constants
# ---------------------------------------------------------------------------
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_REGULATORY_ALERT = "REGULATORY_ALERT"

VALID_SEVERITIES = {
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
    SEVERITY_HIGH,
    SEVERITY_CRITICAL,
    SEVERITY_REGULATORY_ALERT,
}

DEFAULT_RULE_VERSION = "AICTE_APH_2024_25_V1"


class RuleResult(BaseModel):
    rule_code: str
    severity: str
    record_ref: str
    explanation: str
    recommended_action: str
    rule_version: str = DEFAULT_RULE_VERSION
    layer: str = "L3"  # L1, L2, L3


# ---------------------------------------------------------------------------
# Configurable Severity Resolver
# ---------------------------------------------------------------------------

def get_configured_severity(
    db: Optional[Session],
    rule_code: str,
    default_severity: str,
) -> str:
    """
    Resolves severity for a rule:
    Checks rule_severity_configs table for an active override.
    Falls back to default_severity if no configuration exists.
    """
    if db is not None:
        try:
            cfg = (
                db.query(RuleSeverityConfig)
                .filter(RuleSeverityConfig.rule_code == rule_code, RuleSeverityConfig.is_active == True)
                .first()
            )
            if cfg and cfg.severity in VALID_SEVERITIES:
                return cfg.severity
        except Exception:
            pass
    return default_severity


# ---------------------------------------------------------------------------
# Base Rule Definition
# ---------------------------------------------------------------------------

class BaseRule(ABC):
    rule_code: str
    default_severity: str
    name: str
    layer: str  # L1, L2, L3
    rule_version: str = DEFAULT_RULE_VERSION
    description: str

    @classmethod
    def get_severity(cls, db: Optional[Session] = None) -> str:
        return get_configured_severity(db, cls.rule_code, cls.default_severity)

    @abstractmethod
    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        """Evaluates rule against context; returns RuleResult if triggered, else None."""
        pass


# ---------------------------------------------------------------------------
# Layer 1: Identity Rules
# ---------------------------------------------------------------------------

class RuleL1ApaarMissing(BaseRule):
    rule_code = "RULE_L1_APAAR_MISSING"
    default_severity = SEVERITY_WARNING  # WARNING within grace period -> ERROR after grace
    name = "APAAR Identifier Missing"
    layer = "L1"
    description = "Checks if APAAR ID was omitted. Allowed as provisional during active grace period."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        apaar_id = context.get("apaar_id")
        if apaar_id and str(apaar_id).strip():
            return None

        # Check grace period
        admit_date = context.get("admission_date")
        if isinstance(admit_date, datetime):
            dt = admit_date if admit_date.tzinfo else admit_date.replace(tzinfo=timezone.utc)
        elif isinstance(admit_date, str):
            try:
                dt = datetime.strptime(admit_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pass


        policy = evaluate_identity_policy(STATUS_NOT_PROVIDED, admission_date=dt)
        is_expired = policy.get("escalated_error", False)
        base_sev = SEVERITY_ERROR if is_expired else SEVERITY_WARNING
        actual_sev = get_configured_severity(db, self.rule_code, base_sev)

        rec_ref = context.get("record_ref") or context.get("student_name") or "STUDENT_RECORD"
        explanation = (
            f"APAAR missing. Grace period expired."
            if is_expired
            else f"APAAR missing. Active grace period ({policy.get('grace_days_remaining', 30)} days remaining)."
        )
        action = (
            "Student must provide verified APAAR immediately."
            if is_expired
            else "Request student to obtain APAAR identifier before grace period expires."
        )

        return RuleResult(
            rule_code=self.rule_code,
            severity=actual_sev,
            record_ref=str(rec_ref),
            explanation=explanation,
            recommended_action=action,
            layer=self.layer,
        )


class RuleL1BadFormat(BaseRule):
    rule_code = "RULE_L1_BAD_FORMAT"
    default_severity = SEVERITY_ERROR
    name = "APAAR Format or Luhn Checksum Failure"
    layer = "L1"
    description = "Validates that APAAR identifier strictly conforms to 12-digit Luhn mod-10 formula."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        apaar_id = context.get("apaar_id")
        if not apaar_id:
            return None

        if not validate_apaar_format_and_checksum(str(apaar_id)):
            rec_ref = context.get("record_ref") or mask_apaar(str(apaar_id))
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=str(rec_ref),
                explanation="APAAR failed 12-digit format or Luhn mod-10 checksum validation.",
                recommended_action="Verify physical or electronic APAAR card and enter correct check digit.",
                layer=self.layer,
            )
        return None


class RuleL1NotFound(BaseRule):
    rule_code = "RULE_L1_NOT_FOUND"
    default_severity = SEVERITY_ERROR
    name = "APAAR Record Not Found in Directory"
    layer = "L1"
    description = "Triggers if validly formatted APAAR does not exist in the simulated national directory."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        l1_res = context.get("l1_result")
        if l1_res and getattr(l1_res, "reason_code", None) == "NOT_FOUND":
            rec_ref = context.get("record_ref") or mask_apaar(context.get("apaar_id"))
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=str(rec_ref),
                explanation="APAAR ID does not exist in the simulated national directory.",
                recommended_action="Student must verify enrollment in the APAAR registry.",
                layer=self.layer,
            )
        return None


class RuleL1NameDobMismatch(BaseRule):
    rule_code = "RULE_L1_NAME_DOB_MISMATCH"
    default_severity = SEVERITY_WARNING  # Evidence requested
    name = "Name / Date of Birth Demographic Mismatch"
    layer = "L1"
    description = "Triggers when student name or DOB differs from the simulated national registry profile."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        l1_res = context.get("l1_result")
        if l1_res and getattr(l1_res, "reason_code", None) == "MISMATCH":
            rec_ref = context.get("record_ref") or context.get("student_name") or "DEMOGRAPHIC_MATCH"
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=str(rec_ref),
                explanation="Student name or DOB does not match simulated national directory record. Evidence requested.",
                recommended_action="Upload birth certificate or 10th standard certificate for manual review.",
                layer=self.layer,
            )
        return None


class RuleL1ServiceUnavailable(BaseRule):
    rule_code = "RULE_L1_SERVICE_UNAVAILABLE"
    default_severity = SEVERITY_INFO
    name = "Upstream APAAR Service Unavailable (Timeout)"
    layer = "L1"
    description = "Simulates upstream timeout; guarantees record remains provisional and queued for retry."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        l1_res = context.get("l1_result")
        if (l1_res and getattr(l1_res, "status", None) == STATUS_UNAVAILABLE) or context.get("identity_status") == "UNAVAILABLE":
            rec_ref = context.get("record_ref") or "GATEWAY_TIMEOUT"
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=str(rec_ref),
                explanation="Upstream APAAR identity gateway timed out (504). Record stays provisional.",
                recommended_action="Keep record provisional; automated exponential backoff retry is active.",
                layer=self.layer,
            )
        return None


# ---------------------------------------------------------------------------
# Layer 2: Institutional Authority Rules
# ---------------------------------------------------------------------------

class RuleL2ApprovalMissing(BaseRule):
    rule_code = "RULE_L2_APPROVAL_MISSING"
    default_severity = SEVERITY_HIGH
    name = "AICTE Approval Missing for Program/Campus/Shift/Year"
    layer = "L2"
    description = "Verifies that the admitting institution possesses an AICTE Extension of Approval for this branch."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        approval = context.get("approval")
        if not approval:
            rec_ref = f"{context.get('programme')}/{context.get('branch')}/{context.get('academic_year')}"
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=rec_ref,
                explanation=f"No AICTE approval found for programme '{context.get('programme')}', branch '{context.get('branch')}' in academic year '{context.get('academic_year')}'.",
                recommended_action="Verify institutional EoA order; admissions are unauthorized without AICTE approval.",
                layer=self.layer,
            )
        return None


class RuleL2SnapshotMismatch(BaseRule):
    rule_code = "RULE_L2_SNAPSHOT_MISMATCH"
    default_severity = SEVERITY_HIGH
    name = "Approval Snapshot Not Frozen or Superseded"
    layer = "L2"
    description = "Validates that admissions reference an immutable FROZEN AICTE approval snapshot."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        approval: Optional[ProgramApproval] = context.get("approval")
        if approval:
            if approval.status != ApprovalStatus.FROZEN:
                rec_ref = f"APPROVAL-{approval.approval_ref}-v{approval.version}"
                return RuleResult(
                    rule_code=self.rule_code,
                    severity=self.get_severity(db),
                    record_ref=rec_ref,
                    explanation=f"Approval '{approval.approval_ref}' is in DRAFT state and has not been frozen by AICTE.",
                    recommended_action="AICTE Admin must freeze the approved seat matrix before admissions can be committed.",
                    layer=self.layer,
                )
        return None


class RuleL2LateSubmissionWithoutReason(BaseRule):
    rule_code = "RULE_L2_LATE_SUBMISSION_WITHOUT_REASON"
    default_severity = SEVERITY_ERROR
    name = "Submission After Lock Without Mandatory Reason Code"
    layer = "L2"
    description = "Blocks commit of admission records after round lock unless accompanied by an authorized reason code."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        is_locked = context.get("is_locked", False)
        reason_code = context.get("reason_code")
        if is_locked and not reason_code:
            rec_ref = context.get("record_ref") or "ROUND_LOCK"
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=str(rec_ref),
                explanation="Submission submitted after round lock without mandatory late reason code.",
                recommended_action="Provide an official change reason code (e.g., OFFICIAL_CORRECTION, TRANSFER_UPDATE).",
                layer=self.layer,
            )
        return None


# ---------------------------------------------------------------------------
# Layer 3: Seat Compliance Rules
# ---------------------------------------------------------------------------

class RuleL3CapacityExceeded(BaseRule):
    rule_code = "RULE_L3_CAPACITY_EXCEEDED"
    default_severity = SEVERITY_REGULATORY_ALERT  # Opens review case
    name = "Per-Category Approved Seat Capacity Exceeded"
    layer = "L3"
    description = "Triggers regulatory alert when occupied seats (CONFIRMED + ACTIVE) exceed approved quota."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        seat_type = context.get("seat_type", "REGULAR")
        compliance = context.get("seat_compliance")
        if compliance and "by_seat_type" in compliance:
            st_data = compliance["by_seat_type"].get(seat_type)
            if st_data and st_data.get("status") == STATUS_EXCEEDED:
                rec_ref = f"{seat_type}:{st_data.get('occupied')}/{st_data.get('approved')}"
                return RuleResult(
                    rule_code=self.rule_code,
                    severity=self.get_severity(db),
                    record_ref=rec_ref,
                    explanation=f"Approved capacity of {st_data.get('approved')} seats for category '{seat_type}' exceeded (occupied: {st_data.get('occupied')}).",
                    recommended_action="Open AICTE regulatory review case; investigate institution quota overflow.",
                    layer=self.layer,
                )
        return None


class RuleL3ZeroSeatsApproved(BaseRule):
    rule_code = "RULE_L3_ZERO_SEATS_APPROVED"
    default_severity = SEVERITY_REGULATORY_ALERT
    name = "Admission in Category with Zero Approved Seats"
    layer = "L3"
    description = "Triggers when student is admitted into a seat category that has 0 approved seats in the frozen matrix."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        seat_type = context.get("seat_type", "REGULAR")
        compliance = context.get("seat_compliance")
        if compliance and "by_seat_type" in compliance:
            st_data = compliance["by_seat_type"].get(seat_type)
            if not st_data or st_data.get("approved", 0) <= 0:
                rec_ref = f"{seat_type}:0_SEATS"
                return RuleResult(
                    rule_code=self.rule_code,
                    severity=self.get_severity(db),
                    record_ref=rec_ref,
                    explanation=f"Admission attempted under '{seat_type}' which has zero approved seats in AICTE approval.",
                    recommended_action="Cancel unapproved admission or seek AICTE supernumerary quota approval.",
                    layer=self.layer,
                )
        return None


class RuleL3SupernumeraryEvidenceMissing(BaseRule):
    rule_code = "RULE_L3_SUPERNUMERARY_EVIDENCE_MISSING"
    default_severity = SEVERITY_REGULATORY_ALERT
    name = "Supernumerary Seat Missing Required Evidence Reference"
    layer = "L3"
    description = "Enforces that supernumerary allocations (FN, OCI, Gulf Worker) include evidence references."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        seat_type = context.get("seat_type", "")
        evidence_ref = context.get("evidence_ref")
        if "SUPERNUMERARY" in seat_type and not evidence_ref:
            rec_ref = f"{seat_type}:NO_EVIDENCE"
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=rec_ref,
                explanation=f"Supernumerary admission under '{seat_type}' lacks required evidence reference or embassy clearance.",
                recommended_action="Attach valid passport, visa, or PIO/OCI government credential reference.",
                layer=self.layer,
            )
        return None


class RuleL3ContradictoryFlags(BaseRule):
    rule_code = "RULE_L3_CONTRADICTORY_FLAGS"
    default_severity = SEVERITY_ERROR
    name = "Contradictory Nationality / Domicile Flags"
    layer = "L3"
    description = "Detects conflicting flags (NRI vs FN) or contradictions between flags and allocated seat type."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        nri = bool(context.get("nri_flag", False))
        fn = bool(context.get("fn_flag", False))
        oci = bool(context.get("oci_flag", False))
        seat_type = context.get("seat_type", "")

        if nri and fn:
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref="FLAGS_NRI_FN",
                explanation="Contradictory flags: Candidate cannot simultaneously be an NRI and a Foreign National.",
                recommended_action="Correct candidate citizenship flags according to official passport.",
                layer=self.layer,
            )

        if seat_type == "NRI" and not nri:
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref="NRI_FLAG_FALSE",
                explanation="Admission under NRI seat quota requires nri_flag to be True.",
                recommended_action="Set nri_flag to true or reallocate to REGULAR seat type.",
                layer=self.layer,
            )

        if seat_type == "SUPERNUMERARY_FN_OCI_PIO" and not (fn or oci):
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref="FN_OCI_FLAG_FALSE",
                explanation="Admission under SUPERNUMERARY_FN_OCI_PIO quota requires fn_flag or oci_flag to be True.",
                recommended_action="Set fn_flag or oci_flag to true or reallocate to REGULAR seat type.",
                layer=self.layer,
            )

        if seat_type == "REGULAR" and fn:
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref="FN_IN_REGULAR",
                explanation="Foreign National (FN) candidate allocated to a regular approved seat.",
                recommended_action="Allocate candidate under SUPERNUMERARY_FN_OCI_PIO quota.",
                layer=self.layer,
            )

        return None


class RuleL3LateSubmission(BaseRule):
    rule_code = "RULE_L3_LATE_SUBMISSION"
    default_severity = SEVERITY_WARNING
    name = "Late Admission Submission Tagged"
    layer = "L3"
    description = "Tags admissions submitted after round lock with an approved reason code."

    def evaluate(self, db: Session, context: Dict[str, Any]) -> Optional[RuleResult]:
        is_locked = context.get("is_locked", False)
        reason_code = context.get("reason_code")
        if is_locked and reason_code:
            rec_ref = f"LATE_REASON:{reason_code}"
            return RuleResult(
                rule_code=self.rule_code,
                severity=self.get_severity(db),
                record_ref=rec_ref,
                explanation=f"Admission committed post-deadline under authorized reason code: '{reason_code}'.",
                recommended_action="Retain reason documentation for annual AICTE accreditation review.",
                layer=self.layer,
            )
        return None


# ---------------------------------------------------------------------------
# Rule Registry Master List
# ---------------------------------------------------------------------------

ALL_RULES: List[Type[BaseRule]] = [
    # L1 Identity
    RuleL1ApaarMissing,
    RuleL1BadFormat,
    RuleL1NotFound,
    RuleL1NameDobMismatch,
    RuleL1ServiceUnavailable,
    # L2 Authority
    RuleL2ApprovalMissing,
    RuleL2SnapshotMismatch,
    RuleL2LateSubmissionWithoutReason,
    # L3 Compliance
    RuleL3CapacityExceeded,
    RuleL3ZeroSeatsApproved,
    RuleL3SupernumeraryEvidenceMissing,
    RuleL3ContradictoryFlags,
    RuleL3LateSubmission,
]

RULE_CATALOGUE_BY_CODE: Dict[str, Type[BaseRule]] = {r.rule_code: r for r in ALL_RULES}


# ---------------------------------------------------------------------------
# Composite Validation & Verdict Engine
# ---------------------------------------------------------------------------

class LayerReport(BaseModel):
    layer: str
    status: str  # PASSED | FAILED | PENDING | WARNING
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    issues: List[RuleResult]


class ComplianceValidationReport(BaseModel):
    enrollment_id: Optional[str] = None
    record_ref: str
    overall_verdict: str  # VERIFIED | BLOCKED_ERROR | UNDER_REVIEW | PROVISIONAL
    verified: bool
    requires_review: bool
    blocks_commit: bool
    l1_identity: LayerReport
    l2_authority: LayerReport
    l3_compliance: LayerReport
    all_issues: List[RuleResult]


def evaluate_admission_rules(
    db: Session,
    context: Dict[str, Any],
) -> ComplianceValidationReport:
    """
    Executes all registry rules across L1, L2, L3.
    Computes overall verdict:
    - verified = (identity PASSED and authority PASS and compliance PASS)
    - Any ERROR blocks commit of that row.
    - REGULATORY_ALERT and HIGH open a review case and set status to UNDER_REVIEW.
    """
    all_issues: List[RuleResult] = []
    issues_by_layer: Dict[str, List[RuleResult]] = {"L1": [], "L2": [], "L3": []}

    for rule_cls in ALL_RULES:
        rule_instance = rule_cls()
        res = rule_instance.evaluate(db, context)
        if res:
            all_issues.append(res)
            issues_by_layer[res.layer].append(res)

    # Analyze L1
    l1_issues = issues_by_layer["L1"]
    has_l1_error = any(i.severity in (SEVERITY_ERROR, SEVERITY_CRITICAL) for i in l1_issues)
    has_l1_pending = any(i.rule_code == "RULE_L1_SERVICE_UNAVAILABLE" for i in l1_issues) or context.get("identity_status") == "UNAVAILABLE"
    l1_status = "FAILED" if has_l1_error else ("PENDING" if has_l1_pending else ("WARNING" if l1_issues else "PASSED"))

    # Analyze L2
    l2_issues = issues_by_layer["L2"]
    has_l2_error = any(i.severity in (SEVERITY_ERROR, SEVERITY_HIGH, SEVERITY_CRITICAL) for i in l2_issues)
    l2_status = "FAILED" if has_l2_error else ("WARNING" if l2_issues else "PASSED")

    # Analyze L3
    l3_issues = issues_by_layer["L3"]
    has_l3_error = any(i.severity in (SEVERITY_ERROR, SEVERITY_CRITICAL, SEVERITY_REGULATORY_ALERT) for i in l3_issues)
    l3_status = "FAILED" if has_l3_error else ("WARNING" if l3_issues else "PASSED")

    # Overall Verdict Logic
    blocks_commit = any(i.severity in (SEVERITY_ERROR, SEVERITY_CRITICAL) for i in all_issues)
    requires_review = any(i.severity in (SEVERITY_HIGH, SEVERITY_REGULATORY_ALERT) for i in all_issues)
    verified = (l1_status == "PASSED" and l2_status == "PASSED" and l3_status == "PASSED")

    if blocks_commit:
        overall_verdict = "BLOCKED_ERROR"
    elif requires_review:
        overall_verdict = "UNDER_REVIEW"
    elif verified:
        overall_verdict = "VERIFIED"
    else:
        overall_verdict = "PROVISIONAL"

    rec_ref = str(context.get("record_ref") or context.get("enrollment_id") or "ADMISSION_RECORD")

    return ComplianceValidationReport(
        enrollment_id=context.get("enrollment_id"),
        record_ref=rec_ref,
        overall_verdict=overall_verdict,
        verified=verified,
        requires_review=requires_review,
        blocks_commit=blocks_commit,
        l1_identity=LayerReport(
            layer="L1_IDENTITY",
            status=l1_status,
            inputs={
                "apaar_id_provided": bool(context.get("apaar_id")),
                "student_name": context.get("student_name"),
                "date_of_birth": str(context.get("dob") or ""),
            },
            outputs={
                "status": l1_status,
                "issues_count": len(l1_issues),
            },
            issues=l1_issues,
        ),
        l2_authority=LayerReport(
            layer="L2_AUTHORITY",
            status=l2_status,
            inputs={
                "institution_id": context.get("institution_id"),
                "programme": context.get("programme"),
                "branch": context.get("branch"),
                "academic_year": context.get("academic_year"),
            },
            outputs={
                "approval_id": str(context["approval"].id) if context.get("approval") else None,
                "approval_ref": context["approval"].approval_ref if context.get("approval") else None,
                "approval_status": context["approval"].status.value if (context.get("approval") and hasattr(context["approval"].status, "value")) else None,
            },
            issues=l2_issues,
        ),
        l3_compliance=LayerReport(
            layer="L3_COMPLIANCE",
            status=l3_status,
            inputs={
                "seat_type": context.get("seat_type"),
                "category": context.get("category"),
                "nri_flag": context.get("nri_flag"),
                "fn_flag": context.get("fn_flag"),
                "oci_flag": context.get("oci_flag"),
            },
            outputs={
                "seat_compliance": context.get("seat_compliance", {}).get("by_seat_type", {}).get(context.get("seat_type", "REGULAR")),
                "overall_program_status": context.get("seat_compliance", {}).get("overall_status"),
            },
            issues=l3_issues,
        ),
        all_issues=all_issues,
    )


# ---------------------------------------------------------------------------
# Rule Catalogue Markdown Generator
# ---------------------------------------------------------------------------

def generate_rule_catalogue_markdown() -> str:
    """Generates complete documentation of all registered rules for docs/rules.md."""
    lines = [
        "# AICTE Admission Verification Rule Catalogue",
        "",
        "> **Notice:** Generated automatically from code registry (`services/validation_service.py`).",
        "> Reference Handbook: **AICTE Approval Process Handbook (APH)**",
        "",
        "## Severity Levels",
        "",
        "| Severity Level | Description | Behavior |",
        "| :--- | :--- | :--- |",
        "| `INFO` | Advisory notice or telemetry | Stored in audit trail; does not affect lifecycle |",
        "| `WARNING` | Demographic divergence or late tag | Flags evidence requirement; allows provisional status |",
        "| `ERROR` | Severe violation or invalid data | **Blocks commit** of the admission row |",
        "| `HIGH` | Authority snapshot or approval issue | Sets status to `UNDER_REVIEW`; requires human review |",
        "| `CRITICAL` | System integrity or data corruption | Halts processing; alerts security auditor |",
        "| `REGULATORY_ALERT` | Quota overflow or unapproved quota | Opens AICTE ReviewCase; sets `UNDER_REVIEW` |",
        "",
        "---",
        "",
        "## Registered Verification Rules",
        "",
        "| Rule Code | Layer | Name | Default Severity | Description | Recommended Action |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for rule_cls in ALL_RULES:
        lines.append(
            f"| `{rule_cls.rule_code}` | **{rule_cls.layer}** | {rule_cls.name} | `{rule_cls.default_severity}` | {rule_cls.description} | {rule_cls.rule_code} action |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Detailed Rule Specifications",
        "",
    ])

    for rule_cls in ALL_RULES:
        lines.extend([
            f"### `{rule_cls.rule_code}` - {rule_cls.name}",
            f"- **Layer:** {rule_cls.layer}",
            f"- **Default Severity:** `{rule_cls.default_severity}`",
            f"- **Rule Version:** `{rule_cls.rule_version}`",
            f"- **Description:** {rule_cls.description}",
            "",
        ])

    return "\n".join(lines)
