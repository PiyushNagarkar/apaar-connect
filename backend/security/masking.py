"""
Field-Level Privacy Masking Helper (Rule 10).
Returns role-tailored student views with sensitive demographic and identifier fields
masked or removed. Raw encrypted APAAR tokens are NEVER exposed to any caller.
"""
from typing import Any, Dict, Union
from backend.models.student import Student
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_AUDITOR,
    ROLE_VERIFIER,
)


def _to_dict(student: Union[Student, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(student, dict):
        return dict(student)
    return {
        "id": str(student.id),
        "name": student.name,
        "name_normalized": student.name_normalized,
        "dob": student.dob.isoformat() if hasattr(student.dob, "isoformat") else str(student.dob),
        "gender": student.gender,
        "apaar_masked": student.apaar_masked,
        "apaar_hash": student.apaar_hash,
        "mobile_last4": student.mobile_last4,
        "consent_status": student.consent_status,
        "created_at": student.created_at.isoformat() if hasattr(student.created_at, "isoformat") else str(student.created_at),
    }


def mask_student_for_role(
    student: Union[Student, Dict[str, Any]],
    role: str,
    is_own_record: bool = False,
) -> Dict[str, Any]:
    """
    Given a user's role and a student record, returns a sanitized projection.
    Strictly removes raw encrypted APAAR ciphertext across all roles.
    """
    raw = _to_dict(student)

    # 1. STUDENT role
    if role == ROLE_STUDENT:
        if not is_own_record:
            # Students cannot view other students' records
            return {
                "id": raw.get("id"),
                "name": "[REDACTED - ACCESS RESTRICTED]",
                "apaar_masked": "XXXX-XXXX-XXXX",
                "access": "DENIED",
            }
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "dob": raw.get("dob"),
            "gender": raw.get("gender"),
            "apaar_masked": raw.get("apaar_masked", "XXXX-XXXX-XXXX"),
            "mobile_last4": raw.get("mobile_last4"),
            "consent_status": raw.get("consent_status"),
        }

    # 2. INSTITUTION Roles (Admin & Operator)
    if role in [ROLE_INSTITUTION_ADMIN, ROLE_INSTITUTION_OPERATOR]:
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "dob": raw.get("dob"),
            "gender": raw.get("gender"),
            "apaar_masked": raw.get("apaar_masked", "XXXX-XXXX-XXXX"),
            "mobile_last4": raw.get("mobile_last4"),
            "consent_status": raw.get("consent_status"),
            "created_at": raw.get("created_at"),
        }

    # 3. AICTE Administrators & Reviewers
    if role in [ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER]:
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "name_normalized": raw.get("name_normalized"),
            "dob": raw.get("dob"),
            "gender": raw.get("gender"),
            "apaar_masked": raw.get("apaar_masked", "XXXX-XXXX-XXXX"),
            "apaar_hash": raw.get("apaar_hash"),  # Blind index for duplicate adjudication
            "mobile_last4": raw.get("mobile_last4"),
            "consent_status": raw.get("consent_status"),
            "created_at": raw.get("created_at"),
        }

    # 4. AUDITOR: Pseudonymized name, masked DOB, preserved blind index hash for integrity proof
    if role == ROLE_AUDITOR:
        name_parts = str(raw.get("name", "")).split()
        masked_name = " ".join([p[0] + "*" * (len(p) - 1) if len(p) > 1 else p for p in name_parts])
        dob_str = str(raw.get("dob", ""))
        masked_dob = dob_str[:4] + "-XX-XX" if len(dob_str) >= 4 else "XXXX-XX-XX"
        return {
            "id": raw.get("id"),
            "name": masked_name,
            "dob": masked_dob,
            "gender": raw.get("gender"),
            "apaar_masked": raw.get("apaar_masked", "XXXX-XXXX-XXXX"),
            "apaar_hash": raw.get("apaar_hash"),
            "consent_status": raw.get("consent_status"),
        }

    # 5. PUBLIC_VERIFIER or unauthenticated
    return {
        "id": raw.get("id"),
        "apaar_masked": raw.get("apaar_masked", "XXXX-XXXX-XXXX"),
        "verified": True,
    }
