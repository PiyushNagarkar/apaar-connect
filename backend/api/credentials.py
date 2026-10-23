"""
Verifiable Credential API Endpoints (backend/api/credentials.py).

Implements:
- POST /api/credentials: Issuance (verified=True and status in CONFIRMED/ACTIVE/COMPLETED only).
- GET /api/keys: Public Ed25519 key publishing and key rotation.
- GET /api/verify/{reference}: Full 5-step verification pipeline & minimal field disclosure by caller class.
- POST /api/verify/offline (and POST /api/credentials/verify-offline): Offline signature check returning 'Revocation not checked'.
- POST /api/credentials/{id}/revoke: Explicit revocation with mandatory reason.
- GET /api/credentials/{id}/qr.png & qr.svg: Server-side QR codes encoding strictly https://<host>/verify/<public_ref>.
- GET /api/credentials/{id}/certificate: HTML/PDF certificate sample printing 'Student ID + APAAR ID (masked)'.
- POST /api/verifiers/register: Registered verifier registration & API key generation.
- GET /api/verifiers/logs: Verification audit log ('who verified what, when').
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.credential import Credential, RegisteredVerifier, VerificationLog
from backend.schemas.credentials import (
    CredentialIssueRequest,
    CredentialResponse,
    CredentialRevokeRequest,
    OfflineVerifyRequest,
    PublicKeyInfo,
    PublicKeyListResponse,
    RegisteredVerifierCreate,
    RegisteredVerifierResponse,
    VerificationLogResponse,
    VerificationResultResponse,
)
from backend.schemas.errors import AppException, BadRequestError, ForbiddenError, NotFoundError
from backend.security.authz import (
    get_current_user,
    require_authenticated_user,
    require_roles,
    UserPrincipal,
)
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_AUDITOR,
    ROLE_VERIFIER,
)
from backend.services.credential_service import (
    ACTIVE_KEY_ID,
    authenticate_api_key,
    build_verification_url,
    check_verifier_rate_limit,
    generate_qr_png,
    generate_qr_svg,
    issue_credential,
    list_public_keys,
    register_verifier,
    render_certificate_html,
    render_certificate_pdf,
    revoke_credential,
    verify_credential,
    verify_credential_offline,
)

router = APIRouter(tags=["Verifiable Credentials"])


def _extract_client_host(request: Request) -> str:
    """Extracts client host from headers or defaults."""
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}"
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# 1. Issuance: POST /api/credentials
# ---------------------------------------------------------------------------
@router.post(
    "/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a privacy-minimal signed credential",
)
def issue_verifiable_credential(
    req: CredentialIssueRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    """
    Issues an Ed25519-signed credential:
    - ONLY for enrollments with verified=True and status in CONFIRMED, ACTIVE, COMPLETED.
    - Generates 128-bit random public_ref (URL-safe).
    - Signs canonical JSON with Ed25519 private key.
    - Rule 10: No raw APAAR ID in payload.
    """
    host = _extract_client_host(request)
    credential = issue_credential(
        db=db,
        enrollment_id=req.enrollment_id,
        completion_year=req.completion_year,
        qualification=req.qualification,
        expires_in_days=req.expires_in_days,
        host=host,
        actor_id=user.user_id,
    )
    db.commit()

    return CredentialResponse(
        credential_id=str(credential.id),
        enrollment_id=str(credential.enrollment_id),
        public_ref=credential.public_ref,
        status=credential.status,
        payload=credential.payload,
        signature=credential.signature,
        key_id=credential.key_id,
        expires_at=credential.expires_at.isoformat() if credential.expires_at else None,
        revoked_at=credential.revoked_at.isoformat() if credential.revoked_at else None,
        revoke_reason=credential.revoke_reason,
        qr_url=f"/api/credentials/{credential.id}/qr.png",
        verification_url=build_verification_url(credential.public_ref, host=host),
    )


# ---------------------------------------------------------------------------
# 2. Key Rotation & Publishing: GET /api/keys
# ---------------------------------------------------------------------------
@router.get(
    "/keys",
    response_model=PublicKeyListResponse,
    summary="Publish active and rotated public keys for offline signature verification",
)
def get_public_keys():
    """
    Publishes trusted Ed25519 public keys with key_id for rotation.
    Allows external verifiers to perform offline signature validation.
    """
    keys_data = list_public_keys()
    return PublicKeyListResponse(
        active_key_id=ACTIVE_KEY_ID,
        keys=[PublicKeyInfo(**k) for k in keys_data],
    )


# ---------------------------------------------------------------------------
# 3. QR Code Generation: GET /api/credentials/{id}/qr.png & qr.svg
# ---------------------------------------------------------------------------
@router.get("/credentials/{credential_id}/qr.png", summary="Generate server-side PNG QR code")
def get_credential_qr_png(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Encodes strictly https://<host>/verify/<public_ref>.
    Rule 10: Absolutely NO APAAR ID, DOB, contact, or student name in the QR.
    """
    credential = db.query(Credential).filter(
        (Credential.id == credential_id) | (Credential.public_ref == credential_id)
    ).first()
    if not credential:
        raise NotFoundError("Credential not found.")

    host = _extract_client_host(request)
    png_bytes = generate_qr_png(credential.public_ref, host=host)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/credentials/{credential_id}/qr.svg", summary="Generate server-side SVG QR code")
def get_credential_qr_svg(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Encodes strictly https://<host>/verify/<public_ref>.
    Rule 10: Absolutely NO APAAR ID, DOB, contact, or student name in the QR.
    """
    credential = db.query(Credential).filter(
        (Credential.id == credential_id) | (Credential.public_ref == credential_id)
    ).first()
    if not credential:
        raise NotFoundError("Credential not found.")

    host = _extract_client_host(request)
    svg_str = generate_qr_svg(credential.public_ref, host=host)
    return Response(content=svg_str, media_type="image/svg+xml")


@router.get("/credentials/{credential_id}/qr", summary="Generate QR with format param (png/svg)")
def get_credential_qr_by_param(
    credential_id: str,
    request: Request,
    format: str = Query("png", pattern="^(png|svg)$"),
    db: Session = Depends(get_db),
):
    if format == "svg":
        return get_credential_qr_svg(credential_id, request, db)
    return get_credential_qr_png(credential_id, request, db)


# ---------------------------------------------------------------------------
# 4. Verification: GET /api/verify/{reference}
# ---------------------------------------------------------------------------
@router.get(
    "/verify/{reference}",
    response_model=VerificationResultResponse,
    summary="5-Step Verification pipeline with caller class disclosure",
)
def verify_credential_endpoint(
    reference: str,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(get_current_user),
):
    """
    Verifies credential and returns one of:
    VALID | EXPIRED | REVOKED | MALFORMED | UNKNOWN | SERVICE_UNAVAILABLE.

    Steps:
    1. Lookup
    2. Ed25519 Signature check
    3. Expiry check
    4. Revocation check (current server-side)
    5. Consent check (if WITHDRAWN, returns limited response)
    6. Disclose minimal fields by caller class (anonymous / registered verifier / authorised staff)

    Guarantee: SERVICE_UNAVAILABLE must never render as valid.
    """
    # 1. Identify Caller Class
    registered_verifier = None
    caller_class = "anonymous"

    if x_api_key:
        registered_verifier = authenticate_api_key(db, x_api_key)
        if registered_verifier:
            caller_class = "registered_verifier"
            # Rate limit check for registered verifiers
            within_limit = check_verifier_rate_limit(
                str(registered_verifier.id),
                registered_verifier.rate_limit_per_minute,
            )
            if not within_limit:
                raise AppException(
                    code="RATE_LIMIT_EXCEEDED",
                    message="Registered verifier rate limit exceeded. Please retry later.",
                    status_code=429,
                )
        else:
            raise AppException(
                code="INVALID_API_KEY",
                message="Provided X-API-Key is invalid or deactivated.",
                status_code=401,
            )
    elif user.role in [ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_INSTITUTION_ADMIN, ROLE_AUDITOR]:
        caller_class = "authorised_staff"

    # Extract client IP & User Agent for audit logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    result = verify_credential(
        db=db,
        reference=reference,
        caller_class=caller_class,
        registered_verifier=registered_verifier,
        user_principal=user,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.commit()

    # Constraint: SERVICE_UNAVAILABLE must NEVER render as valid
    if result["status"] == "SERVICE_UNAVAILABLE":
        result["valid"] = False
        return JSONResponse(status_code=503, content=result)

    return result


# ---------------------------------------------------------------------------
# 5. Offline Signature Verification: POST /api/verify/offline
# ---------------------------------------------------------------------------
@router.post(
    "/verify/offline",
    response_model=VerificationResultResponse,
    summary="Verify Ed25519 signature offline, returning 'Revocation not checked'",
)
@router.post(
    "/credentials/verify-offline",
    response_model=VerificationResultResponse,
    include_in_schema=False,
)
def verify_offline_endpoint(req: OfflineVerifyRequest):
    """
    Verifies credential offline by signature only.
    Strictly returns warning: 'Revocation not checked'.
    """
    res = verify_credential_offline(
        payload=req.payload,
        signature=req.signature,
        key_id=req.key_id,
    )
    return VerificationResultResponse(
        status=res["status"],
        valid=res["valid"],
        reference=req.payload.get("public_ref", "OFFLINE_PAYLOAD"),
        caller_class="offline_verifier",
        warning=res.get("warning"),
        message=res.get("message") or res.get("warning"),
        key_id=res.get("key_id"),
        disclosed=req.payload if res["valid"] else None,
    )


# ---------------------------------------------------------------------------
# 6. Revocation: POST /api/credentials/{id}/revoke
# ---------------------------------------------------------------------------
@router.post(
    "/credentials/{credential_id}/revoke",
    response_model=Dict[str, Any],
    summary="Revoke credential with a mandatory reason",
)
def revoke_credential_endpoint(
    credential_id: str,
    req: CredentialRevokeRequest,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_INSTITUTION_ADMIN)),
):
    """
    Explicitly revokes a verifiable credential:
    - Mandatory reason required (returns 400 Bad Request if missing/empty).
    - Revocation status is reflected immediately on refresh.
    """
    cred = revoke_credential(
        db=db,
        credential_id_or_ref=credential_id,
        reason=req.reason,
        actor_id=user.user_id,
    )
    db.commit()

    return {
        "credential_id": str(cred.id),
        "public_ref": cred.public_ref,
        "status": "REVOKED",
        "revoked_at": cred.revoked_at.isoformat() if cred.revoked_at else None,
        "revoke_reason": cred.revoke_reason,
        "message": "Credential successfully revoked. Subsequent verifications will return REVOKED.",
    }


# ---------------------------------------------------------------------------
# 7. Registered Verifiers: POST /api/verifiers/register
# ---------------------------------------------------------------------------
@router.post(
    "/verifiers/register",
    response_model=RegisteredVerifierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a third-party verifier and generate API key",
)
@router.post(
    "/credentials/verifiers/register",
    response_model=RegisteredVerifierResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def register_verifier_endpoint(
    req: RegisteredVerifierCreate,
    db: Session = Depends(get_db),
):
    """
    Registers a third-party verifier:
    - Stores declared purpose and field disclosure policy.
    - Generates and returns cryptographically secure API key (shown once).
    - Stores SHA-256 hash in database.
    """
    verifier, api_key = register_verifier(
        db=db,
        name=req.name,
        contact_email=req.contact_email,
        declared_purpose=req.declared_purpose,
        rate_limit_per_minute=req.rate_limit_per_minute or 60,
        allowed_fields=req.allowed_fields,
    )
    db.commit()

    return RegisteredVerifierResponse(
        verifier_id=str(verifier.id),
        name=verifier.name,
        contact_email=verifier.contact_email,
        declared_purpose=verifier.declared_purpose,
        api_key=api_key,
        api_key_prefix=verifier.api_key_prefix,
        rate_limit_per_minute=verifier.rate_limit_per_minute,
        allowed_fields=verifier.allowed_fields,
        is_active=verifier.is_active,
        created_at=verifier.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# 8. Verification Audit Logs: GET /api/verifiers/logs
# ---------------------------------------------------------------------------
@router.get(
    "/verifiers/logs",
    response_model=List[VerificationLogResponse],
    summary="Audit log of verification attempts: who verified what, when",
)
@router.get(
    "/credentials/verification-logs",
    response_model=List[VerificationLogResponse],
    include_in_schema=False,
)
def get_verification_logs_endpoint(
    reference: Optional[str] = Query(None, description="Filter by credential reference"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_roles(ROLE_AICTE_ADMIN, ROLE_AICTE_REVIEWER, ROLE_AUDITOR)),
):
    """Returns historical verification attempts for audit inspection."""
    query = db.query(VerificationLog)
    if reference:
        query = query.filter(VerificationLog.reference == reference.strip())
    logs = query.order_by(VerificationLog.created_at.desc()).limit(limit).all()

    return [
        VerificationLogResponse(
            id=str(log.id),
            reference=log.reference,
            verifier_class=log.verifier_class,
            verifier_id=log.verifier_id,
            verifier_name=log.verifier_name,
            purpose=log.purpose,
            result_status=log.result_status,
            disclosed_fields=log.disclosed_fields,
            verified_at=log.created_at.isoformat(),
        )
        for log in logs
    ]


# ---------------------------------------------------------------------------
# 9. Certificate Sample Template (Requirement 10: Student ID + APAAR ID masked)
# ---------------------------------------------------------------------------
@router.get(
    "/credentials/{credential_id}/certificate",
    summary="Sample certificate HTML/PDF template printing 'Student ID + APAAR ID (masked)'",
)
def get_certificate_template(
    credential_id: str,
    request: Request,
    format: str = Query("html", pattern="^(html|pdf|json)$"),
    db: Session = Depends(get_db),
):
    """
    Renders certificate template displaying 'Student ID + APAAR ID (masked)' (Rule 10).
    Available as:
    - HTML (default): Printable responsive HTML certificate with embedded QR.
    - PDF: Standard PDF 1.4 document.
    - JSON: Structured claims and verification references.
    """
    credential = db.query(Credential).filter(
        (Credential.id == credential_id) | (Credential.public_ref == credential_id)
    ).first()
    if not credential:
        raise NotFoundError("Credential not found.")

    host = _extract_client_host(request)

    if format == "pdf":
        pdf_bytes = render_certificate_pdf(credential, host=host)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=certificate-{credential.public_ref}.pdf"},
        )

    if format == "json":
        enrollment = credential.enrollment
        student = enrollment.student if enrollment else None
        return {
            "title": "Verifiable Academic Enrollment Credential",
            "student_display_name": credential.payload.get("student_display_name"),
            "student_id": str(student.id) if student else None,
            "apaar_masked": student.apaar_masked if student else "XXXX-XXXX-XXXX",
            "institution_name": credential.payload.get("institution_name"),
            "qualification": credential.payload.get("qualification"),
            "public_ref": credential.public_ref,
            "status": credential.status,
            "verification_url": build_verification_url(credential.public_ref, host=host),
            "key_id": credential.key_id,
        }

    html_content = render_certificate_html(credential, host=host)
    return HTMLResponse(content=html_content)


# ---------------------------------------------------------------------------
# 10. Credential Detail: GET /api/credentials/{id}
# ---------------------------------------------------------------------------
@router.get(
    "/credentials/{credential_id}",
    response_model=CredentialResponse,
    summary="Get credential metadata and payload",
)
def get_credential_by_id(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: UserPrincipal = Depends(require_authenticated_user),
):
    credential = db.query(Credential).filter(
        (Credential.id == credential_id) | (Credential.public_ref == credential_id)
    ).first()
    if not credential:
        raise NotFoundError("Credential not found.")

    host = _extract_client_host(request)
    return CredentialResponse(
        credential_id=str(credential.id),
        enrollment_id=str(credential.enrollment_id),
        public_ref=credential.public_ref,
        status=credential.status,
        payload=credential.payload,
        signature=credential.signature,
        key_id=credential.key_id,
        expires_at=credential.expires_at.isoformat() if credential.expires_at else None,
        revoked_at=credential.revoked_at.isoformat() if credential.revoked_at else None,
        revoke_reason=credential.revoke_reason,
        qr_url=f"/api/credentials/{credential.id}/qr.png",
        verification_url=build_verification_url(credential.public_ref, host=host),
    )
