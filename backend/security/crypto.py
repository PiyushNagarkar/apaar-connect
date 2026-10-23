import base64
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt
from backend.schemas.errors import AppException

SECRET_KEY = os.getenv("SECRET_KEY", "aicte_apaar_connect_super_secret_jwt_key_2025_x99")
APAAR_ENCRYPTION_KEY = os.getenv("APAAR_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
APAAR_KEYED_HASH_SALT = os.getenv("APAAR_KEYED_HASH_SALT", "aicte_blind_index_salt_keyed_hmac_sha256_v1")

import bcrypt


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


class ExpiredTokenError(AppException):
    def __init__(self, message: str = "Token has expired. Please log in again."):
        super().__init__(code="TOKEN_EXPIRED", message=message, status_code=401)


class InvalidTokenError(AppException):
    def __init__(self, message: str = "Invalid authentication token."):
        super().__init__(code="TOKEN_INVALID", message=message, status_code=401)


def create_jwt(data: Dict[str, Any], expires_minutes: int = 15) -> str:
    """Creates short-lived JWT access token (default 15 minutes)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str) -> Dict[str, Any]:
    """Decodes JWT access token; raises ExpiredTokenError or InvalidTokenError if invalid."""
    if not token:
        raise InvalidTokenError("Missing token.")
    try:
        from jose.exceptions import ExpiredSignatureError
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise ExpiredTokenError("Authentication token has expired.")
    except JWTError as e:
        raise InvalidTokenError(f"Could not validate credentials: {str(e)}")


def _get_aesgcm() -> AESGCM:
    key_bytes = bytes.fromhex(APAAR_ENCRYPTION_KEY[:64])
    return AESGCM(key_bytes)


def normalize_apaar(raw_apaar: str) -> str:
    if not raw_apaar:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", str(raw_apaar)).strip()


def encrypt_apaar(raw_apaar: str) -> str:
    """Rule 10: AES-256-GCM authenticated encryption."""
    norm = normalize_apaar(raw_apaar)
    if not norm:
        return ""
    cipher = _get_aesgcm()
    nonce = os.urandom(12)
    ciphertext = cipher.encrypt(nonce, norm.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_apaar(encrypted_token: str) -> str:
    """Rule 10: AES-256-GCM decryption."""
    if not encrypted_token:
        return ""
    try:
        raw = base64.urlsafe_b64decode(encrypted_token.encode("utf-8"))
        if len(raw) < 12:
            return ""
        nonce = raw[:12]
        ciphertext = raw[12:]
        cipher = _get_aesgcm()
        decrypted = cipher.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception:
        return ""


def compute_apaar_hash(raw_apaar: str) -> str:
    """Rule 10: Deterministic HMAC-SHA256 blind index for exact duplicate lookups without decrypting."""
    norm = normalize_apaar(raw_apaar)
    if not norm:
        return ""
    return hmac.new(APAAR_KEYED_HASH_SALT.encode("utf-8"), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_apaar(raw_apaar: str) -> str:
    """Rule 10: Masked display representation XXXX-XXXX-1234."""
    norm = normalize_apaar(raw_apaar)
    if not norm:
        return "XXXX-XXXX-XXXX"
    if len(norm) >= 4:
        return f"XXXX-XXXX-{norm[-4:]}"
    return f"XXXX-XXXX-{norm}"
