import json
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from backend.models.credential import Credential
from backend.models.enrollment import Enrollment
from backend.services.credential_service import (
    ACTIVE_KEY_ID,
    CREDENTIAL_KEY_ID,
    ELIGIBLE_ISSUANCE_STATUSES,
    get_signing_key,
    get_public_key,
    list_public_keys,
    canonical_json_bytes,
    sign_payload_ed25519,
    verify_payload_signature,
    generate_128bit_public_ref,
    build_verification_url,
    generate_qr_svg,
    generate_qr_png,
    issue_credential,
    verify_credential,
    verify_credential_offline,
    revoke_credential,
    auto_revoke_credential_for_enrollment,
    register_verifier,
    authenticate_api_key,
    check_verifier_rate_limit,
    render_certificate_html,
    render_certificate_pdf,
)

logger = logging.getLogger(__name__)


def sign_payload(payload: dict) -> str:
    """Produces cryptographic signature over canonical JSON payload."""
    priv, _, _ = get_signing_key()
    return sign_payload_ed25519(payload, priv)


def issue_verifiable_credential(
    db: Session,
    enrollment: Enrollment,
) -> Credential:
    """Issues a privacy-minimal signed credential for a verified student."""
    return issue_credential(db=db, enrollment_id=str(enrollment.id))


def verify_credential_signature(credential: Credential) -> bool:
    """Verifies that the credential signature matches its payload."""
    pub = get_public_key(credential.key_id)
    if not pub:
        return False
    return verify_payload_signature(credential.payload, credential.signature, pub)

