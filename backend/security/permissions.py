"""
Permission Matrix and Role-Based Access Control (RBAC) definitions.
Maps System Roles to Allowed Actions and Granular Permissions.
"""
from typing import Dict, Set

# System Roles
ROLE_AICTE_ADMIN = "AICTE_ADMIN"
ROLE_AICTE_REVIEWER = "AICTE_REVIEWER"
ROLE_INSTITUTION_ADMIN = "INSTITUTION_ADMIN"
ROLE_INSTITUTION_OPERATOR = "INSTITUTION_OPERATOR"
ROLE_STUDENT = "STUDENT"
ROLE_AUDITOR = "AUDITOR"
ROLE_VERIFIER = "VERIFIER"

ALL_ROLES = {
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_AUDITOR,
    ROLE_VERIFIER,
}

# Granular Actions
ACTION_APPROVAL_CREATE = "APPROVAL_CREATE"
ACTION_APPROVAL_EDIT = "APPROVAL_EDIT"
ACTION_APPROVAL_FREEZE = "APPROVAL_FREEZE"
ACTION_APPROVAL_READ = "APPROVAL_READ"

ACTION_SEAT_ALLOCATION_EDIT = "SEAT_ALLOCATION_EDIT"
ACTION_SEAT_ALLOCATION_READ = "SEAT_ALLOCATION_READ"

ACTION_ENROLLMENT_SUBMIT = "ENROLLMENT_SUBMIT"
ACTION_ENROLLMENT_READ = "ENROLLMENT_READ"
ACTION_ENROLLMENT_WRITE = "ENROLLMENT_WRITE"

ACTION_REVIEW_READ = "REVIEW_READ"
ACTION_REVIEW_DECIDE = "REVIEW_DECIDE"

ACTION_STUDENT_READ_OWN = "STUDENT_READ_OWN"
ACTION_STUDENT_READ_ANY = "STUDENT_READ_ANY"

ACTION_CREDENTIAL_ISSUE = "CREDENTIAL_ISSUE"
ACTION_CREDENTIAL_REVOKE = "CREDENTIAL_REVOKE"
ACTION_CREDENTIAL_VERIFY = "CREDENTIAL_VERIFY"

ACTION_AUDIT_LOG_READ = "AUDIT_LOG_READ"

# Role -> Set of Allowed Actions Permission Matrix
PERMISSION_MATRIX: Dict[str, Set[str]] = {
    # 1. AICTE_ADMIN: Full administrative authority over approvals, rules, quotas, and verifications
    ROLE_AICTE_ADMIN: {
        ACTION_APPROVAL_CREATE,
        ACTION_APPROVAL_EDIT,
        ACTION_APPROVAL_FREEZE,
        ACTION_APPROVAL_READ,
        ACTION_SEAT_ALLOCATION_EDIT,
        ACTION_SEAT_ALLOCATION_READ,
        ACTION_ENROLLMENT_SUBMIT,
        ACTION_ENROLLMENT_READ,
        ACTION_ENROLLMENT_WRITE,
        ACTION_REVIEW_READ,
        ACTION_REVIEW_DECIDE,
        ACTION_STUDENT_READ_OWN,
        ACTION_STUDENT_READ_ANY,
        ACTION_CREDENTIAL_ISSUE,
        ACTION_CREDENTIAL_REVOKE,
        ACTION_CREDENTIAL_VERIFY,
        ACTION_AUDIT_LOG_READ,
    },

    # 2. AICTE_REVIEWER: Can decide review cases, view enrollments/approvals; CANNOT create/edit approvals or allocations
    ROLE_AICTE_REVIEWER: {
        ACTION_APPROVAL_READ,
        ACTION_SEAT_ALLOCATION_READ,
        ACTION_ENROLLMENT_READ,
        ACTION_REVIEW_READ,
        ACTION_REVIEW_DECIDE,  # Allowed to adjudicate flagged duplicate/overflow cases
        ACTION_STUDENT_READ_ANY,
        ACTION_CREDENTIAL_VERIFY,
    },

    # 3. INSTITUTION_ADMIN: Manages own institution admissions; CANNOT edit approvals or seat quotas
    ROLE_INSTITUTION_ADMIN: {
        ACTION_APPROVAL_READ,
        ACTION_SEAT_ALLOCATION_READ,
        ACTION_ENROLLMENT_SUBMIT,
        ACTION_ENROLLMENT_READ,
        ACTION_ENROLLMENT_WRITE,
        ACTION_REVIEW_READ,
        ACTION_STUDENT_READ_OWN,
        ACTION_CREDENTIAL_ISSUE,
        ACTION_CREDENTIAL_VERIFY,
    },

    # 4. INSTITUTION_OPERATOR: Uploads and commits admission batches for own institution only; cannot edit allocations
    ROLE_INSTITUTION_OPERATOR: {
        ACTION_APPROVAL_READ,
        ACTION_SEAT_ALLOCATION_READ,
        ACTION_ENROLLMENT_SUBMIT,
        ACTION_ENROLLMENT_READ,
        ACTION_ENROLLMENT_WRITE,
        ACTION_CREDENTIAL_VERIFY,
    },

    # 5. STUDENT: Read-only access strictly to own admission and issued credential; no write actions
    ROLE_STUDENT: {
        ACTION_STUDENT_READ_OWN,
        ACTION_CREDENTIAL_VERIFY,
    },

    # 6. AUDITOR: Complete read-only access across all institutions, approvals, enrollments, and tamper-evident audit logs; NO WRITE ACTIONS
    ROLE_AUDITOR: {
        ACTION_APPROVAL_READ,
        ACTION_SEAT_ALLOCATION_READ,
        ACTION_ENROLLMENT_READ,
        ACTION_REVIEW_READ,
        ACTION_STUDENT_READ_ANY,
        ACTION_AUDIT_LOG_READ,
        ACTION_CREDENTIAL_VERIFY,
    },

    # 7. VERIFIER: Public QR verifier checking cryptographic validity of student credentials
    ROLE_VERIFIER: {
        ACTION_CREDENTIAL_VERIFY,
    },
}


def has_permission(role: str, action: str) -> bool:
    """Checks whether the specified role is granted the given action."""
    allowed_actions = PERMISSION_MATRIX.get(role, set())
    return action in allowed_actions
