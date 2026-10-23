"""
Pydantic Schemas for Privacy (Consent, Processing Basis, Access Events),
Evidence (Upload, SHA-256 Checksums, Signed URLs), and Audit (Hash Chains, Retention Policies).
backend/schemas/privacy_evidence_audit.py
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Consent & Processing Basis Schemas
# ---------------------------------------------------------------------------
class ConsentRecordCreate(BaseModel):
    student_id: str = Field(..., description="UUID of student")
    purpose: str = Field(..., description="ADMISSION_REPORTING, VERIFICATION, or REGULATORY_MONITORING")
    consent_status: str = Field(..., description="GRANTED, PENDING, WITHDRAWN, or NOT_REQUIRED")
    reference: Optional[str] = Field(None, description="Optional consent capture reference (e.g., OTP ID or form number)")


class ConsentRecordResponse(BaseModel):
    id: str
    student_id: str
    purpose: str
    consent_status: str
    reference: str
    timestamp: datetime
    created_at: datetime


class ConsentToggleRequest(BaseModel):
    purpose: str = Field(..., description="Target purpose to toggle")
    consent_status: str = Field(..., description="New consent status: GRANTED | WITHDRAWN")


class ProcessingBasisRecordCreate(BaseModel):
    basis_type: str = Field(..., description="STATUTORY_MANDATE, LEGAL_OBLIGATION, PUBLIC_INTEREST, REGULATORY_COMPLIANCE")
    statute_reference: str = Field(..., description="Legal citation, e.g. 'AICTE Act 1987 Section 10(k)'")
    purpose: str = Field(..., description="ADMISSION_REPORTING, VERIFICATION, REGULATORY_MONITORING")
    description: str = Field(..., description="Detailed explanation of legal basis and necessity")
    institution_id: Optional[str] = Field(None, description="Associated institution or null for national regulatory basis")
    student_id: Optional[str] = Field(None, description="Optional student link or null for general mandate")
    valid_from: Optional[datetime] = Field(None, description="Start date of statutory applicability")
    valid_until: Optional[datetime] = Field(None, description="Optional sunset date")


class ProcessingBasisRecordResponse(BaseModel):
    id: str
    institution_id: Optional[str] = None
    student_id: Optional[str] = None
    basis_type: str
    statute_reference: str
    purpose: str
    description: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    is_active: bool
    created_by: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# 2. Access Events Schemas
# ---------------------------------------------------------------------------
class AccessEventResponse(BaseModel):
    id: str
    actor_id: str
    actor_role: str
    record_type: str
    record_id: str
    purpose: str
    fields_accessed: Optional[List[str]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    accessed_at: datetime


# ---------------------------------------------------------------------------
# 3. Evidence Schemas
# ---------------------------------------------------------------------------
class EvidenceRegisterRequest(BaseModel):
    reference: str = Field(..., description="Associated record identifier (e.g. enrollment ID or case reference)")
    evidence_type: str = Field(..., description="IDENTITY, APPROVAL, ADMISSION_CATEGORY, or COMPLETION")
    filename: str = Field(..., description="Filename including extension")
    sha256_hash: Optional[str] = Field(None, description="Precomputed client-side SHA-256 checksum if uploading metadata only")
    mime_type: Optional[str] = Field("application/pdf", description="MIME content type")
    file_size_bytes: Optional[int] = Field(0, description="File size in bytes")


class EvidenceResponse(BaseModel):
    id: str
    reference: str
    sha256_hash: str
    evidence_type: str
    uploader_id: str
    filename: str
    mime_type: str
    file_size_bytes: int
    virus_scan_status: str
    virus_scan_report: Optional[str] = None
    signed_download_url: str
    created_at: datetime


# ---------------------------------------------------------------------------
# 4. Audit & Hash Chain Schemas
# ---------------------------------------------------------------------------
class AuditEventResponse(BaseModel):
    id: str
    actor_id: str
    institution_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    reason: str
    request_id: str
    prev_hash: Optional[str] = None
    hash: Optional[str] = None
    created_at: datetime


class AuditChainVerifyResponse(BaseModel):
    chain_valid: bool
    total_events_checked: int
    genesis_hash: Optional[str] = None
    tail_hash: Optional[str] = None
    broken_links: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# 5. Retention Policy Schemas
# ---------------------------------------------------------------------------
class RetentionPolicyResponse(BaseModel):
    id: str
    record_category: str
    retention_days: int
    legal_basis: str
    statutory_rule: Optional[str] = None
    action_on_expiry: str
    description: Optional[str] = None
    is_active: bool
    updated_by: Optional[str] = None
    updated_at: datetime


class RetentionPolicyUpdateRequest(BaseModel):
    retention_days: int = Field(..., ge=1, le=36500, description="Retention duration in days")
    legal_basis: Optional[str] = Field(None, description="Regulatory justification")
    statutory_rule: Optional[str] = Field(None, description="Statutory rule identifier")
    action_on_expiry: Optional[str] = Field(None, description="PURGE, ANONYMIZE, or ARCHIVE")
    description: Optional[str] = Field(None, description="Policy notes")
    is_active: Optional[bool] = Field(None, description="Active status")
