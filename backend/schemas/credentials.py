"""
Pydantic Schemas for Credential Issuance, Verification, and Registered Verifiers.
backend/schemas/credentials.py
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CredentialIssueRequest(BaseModel):
    enrollment_id: str = Field(..., description="UUID of the verified enrollment")
    completion_year: Optional[int] = Field(None, description="Year of programme completion if applicable")
    qualification: Optional[str] = Field(None, description="Optional override for qualification/branch title")
    expires_in_days: Optional[int] = Field(None, description="Optional expiration duration in days (e.g., 1460 for 4 years)")


class CredentialPayload(BaseModel):
    credential_id: str
    public_ref: str
    student_display_name: str
    qualification: str
    institution_name: str
    completion_year: Optional[int] = None
    status_at_issue: str
    issued_at: str
    expires_at: Optional[str] = None
    key_id: str


class CredentialResponse(BaseModel):
    credential_id: str
    enrollment_id: str
    public_ref: str
    status: str
    payload: Dict[str, Any]
    signature: str
    key_id: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoke_reason: Optional[str] = None
    qr_url: str
    verification_url: str


class CredentialRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for revoking the verifiable credential")


class VerificationResultResponse(BaseModel):
    status: str = Field(..., description="VALID | EXPIRED | REVOKED | MALFORMED | UNKNOWN | SERVICE_UNAVAILABLE | VALID_OFFLINE")
    valid: bool
    reference: str
    caller_class: Optional[str] = None  # anonymous, registered_verifier, authorised_staff
    message: Optional[str] = None
    warning: Optional[str] = None  # e.g. "Revocation not checked"
    consent_status: Optional[str] = None
    limited_response: Optional[bool] = None
    disclosed: Optional[Dict[str, Any]] = None
    revoked_at: Optional[str] = None
    revoke_reason: Optional[str] = None
    expired_at: Optional[str] = None
    key_id: Optional[str] = None


class OfflineVerifyRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Canonical credential payload dict")
    signature: str = Field(..., description="Ed25519 signature base64 string")
    key_id: Optional[str] = Field(None, description="Key identifier for signature verification")


class RegisteredVerifierCreate(BaseModel):
    name: str = Field(..., description="Organization or employer name")
    contact_email: str = Field(..., description="Official contact email")
    declared_purpose: str = Field(..., description="Declared purpose e.g. EMPLOYMENT_BACKGROUND_CHECK, ACADEMIC_ADMISSION, KYC")
    rate_limit_per_minute: Optional[int] = Field(60, description="Allowed verification queries per minute")
    allowed_fields: Optional[List[str]] = Field(None, description="List of permitted claim fields to disclose")


class RegisteredVerifierResponse(BaseModel):
    verifier_id: str
    name: str
    contact_email: str
    declared_purpose: str
    api_key: Optional[str] = None  # Only exposed at creation time
    api_key_prefix: str
    rate_limit_per_minute: int
    allowed_fields: Optional[List[str]] = None
    is_active: bool
    created_at: str


class PublicKeyInfo(BaseModel):
    key_id: str
    algorithm: str = "Ed25519"
    public_key: str
    public_key_pem: str
    status: str = "ACTIVE"


class PublicKeyListResponse(BaseModel):
    active_key_id: str
    keys: List[PublicKeyInfo]


class VerificationLogResponse(BaseModel):
    id: str
    reference: str
    verifier_class: str
    verifier_id: Optional[str] = None
    verifier_name: Optional[str] = None
    purpose: Optional[str] = None
    result_status: str
    disclosed_fields: Optional[List[str]] = None
    verified_at: str
