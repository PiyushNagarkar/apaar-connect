"""
Identity Provider Service and Simulated APAAR Adapter (MOCK_APAAR_V1).
Implements:
- Abstract IdentityProvider interface
- MockApaarProvider with deterministic registry and synthetic Luhn-like checksum
- Config flag provider factory
- Name normalization + similarity matching ("Aarav  Sharma" ~ "AARAV SHARMA")
- Exponential backoff retry simulator
- Policy engine with configurable grace period for NOT_PROVIDED and UNAVAILABLE handling
- Rule 10: Never logs full APAAR IDs (always masked)
"""
import asyncio
import json
import logging
import os
import re
import unicodedata
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from backend.models.identity import IdentityCheck
from backend.security.crypto import mask_apaar

logger = logging.getLogger("identity_adapter")

# Provider Constants (Rule 1)
SOURCE_MOCK_APAAR = "MOCK_APAAR_V1"

# Status Enums
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_PENDING = "PENDING"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_NOT_PROVIDED = "NOT_PROVIDED"

# Reason Codes
REASON_MATCH_CONFIRMED = "MATCH_CONFIRMED"
REASON_NOT_PROVIDED = "NOT_PROVIDED"
REASON_FORMAT = "FORMAT"
REASON_NOT_FOUND = "NOT_FOUND"
REASON_MISMATCH = "MISMATCH"
REASON_TIMEOUT = "UNAVAILABLE"
REASON_PENDING = "PENDING"


# ---------------------------------------------------------------------------
# Output Schemas
# ---------------------------------------------------------------------------

class IdentityCheckResult(BaseModel):
    check_id: str
    request_id: str
    source: str = SOURCE_MOCK_APAAR
    status: str  # PASSED, FAILED, PENDING, UNAVAILABLE, NOT_PROVIDED
    exists: Optional[bool] = None      # Never fake unchecked fields; use null
    name_match: Optional[bool] = None  # Never fake unchecked fields; use null
    dob_match: Optional[bool] = None   # Never fake unchecked fields; use null
    checked_at: str
    reason_code: str
    raw_details: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Format Validation & Luhn-like Checksum
# ---------------------------------------------------------------------------

def validate_apaar_format_and_checksum(raw_apaar: Optional[str]) -> bool:
    """
    Validates synthetic 12-digit APAAR format with a deterministic Luhn-like checksum.
    Digits must be strictly 12 numbers and satisfy mod 10 Luhn formula.
    """
    if not raw_apaar or not isinstance(raw_apaar, str):
        return False
    digits = re.sub(r"[\s\-]+", "", raw_apaar.strip())
    if not re.fullmatch(r"\d{12}", digits):
        return False

    total = 0
    for idx, char in enumerate(reversed(digits)):
        d = int(char)
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (total % 10 == 0)


def compute_luhn_checksum_digit(eleven_digits: str) -> str:
    """Calculates check digit for 11 digits to construct a valid 12-digit APAAR."""
    cleaned = re.sub(r"\D", "", eleven_digits)[:11].zfill(11)
    total = 0
    for idx, char in enumerate(reversed(cleaned), start=1):
        d = int(char)
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check_digit = (10 - (total % 10)) % 10
    return str(check_digit)


def generate_valid_apaar(prefix_11: str = "98765432101") -> str:
    """Generates a mathematically valid 12-digit synthetic APAAR ID."""
    prefix = re.sub(r"\D", "", prefix_11)[:11].zfill(11)
    return prefix + compute_luhn_checksum_digit(prefix)


# ---------------------------------------------------------------------------
# Name Normalization and Similarity Matching
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """
    Normalizes student name: collapses whitespace, strips honorifics, removes special chars.
    'Aarav  Sharma' -> 'AARAV SHARMA'
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name)).strip().upper()
    # Strip common titles
    for title in ["MR.", "MR", "MS.", "MS", "MRS.", "MRS", "DR.", "DR", "KUMAR", "KUMARI"]:
        if text.startswith(title + " "):
            text = text[len(title) + 1:].strip()
    # Replace non-letters with spaces and collapse
    text = re.sub(r"[^A-Z\s]", " ", text)
    return " ".join(text.split())


def check_name_similarity(input_name: str, registry_name: str, threshold: float = 0.85) -> bool:
    """
    Checks if normalized names match or satisfy similarity threshold.
    Supports token reordering ('Aarav Sharma' == 'Sharma Aarav') and whitespace normalization.
    """
    norm_in = normalize_name(input_name)
    norm_reg = normalize_name(registry_name)
    if not norm_in or not norm_reg:
        return False
    if norm_in == norm_reg:
        return True
    # Token set equality
    if set(norm_in.split()) == set(norm_reg.split()):
        return True
    return SequenceMatcher(None, norm_in, norm_reg).ratio() >= threshold


def check_dob_match(input_dob: Any, registry_dob: Any) -> bool:
    """Matches date of birth against registry (exact YYYY-MM-DD)."""
    if not input_dob or not registry_dob:
        return False
    str_in = str(input_dob).strip()[:10]
    str_reg = str(registry_dob).strip()[:10]
    return str_in == str_reg


# ---------------------------------------------------------------------------
# Synthetic APAAR Registry Data
# ---------------------------------------------------------------------------

SYNTHETIC_REGISTRY: Dict[str, Dict[str, Any]] = {
    # Valid synthetic APAAR IDs (matching Luhn checksum or registered demo profiles)
    "987654321015": {
        "name": "Priya Patel",
        "dob": "2005-03-21",
        "gender": "FEMALE",
        "status": "ACTIVE",
    },
    "987654321012": {
        "name": "Priya Patel",
        "dob": "2005-03-21",
        "gender": "FEMALE",
        "status": "ACTIVE",
    },
    "987654321013": {
        "name": "Rahul Sharma",
        "dob": "2004-11-05",
        "gender": "MALE",
        "status": "ACTIVE",
    },
    "987654321014": {
        "name": "Ananya Iyer",
        "dob": "2005-01-19",
        "gender": "FEMALE",
        "status": "ACTIVE",
    },
    "123456789012": {
        "name": "Aarav Sharma",
        "dob": "2004-05-14",
        "gender": "MALE",
        "status": "ACTIVE",
    },
    "111122223333": {
        "name": "Vikram Singh",
        "dob": "2004-08-12",
        "gender": "MALE",
        "status": "ACTIVE",
    },
}


def load_synthetic_registry(path: Optional[str] = None) -> int:
    """Loads additional synthetic APAAR registry records from a JSON file into SYNTHETIC_REGISTRY."""
    global SYNTHETIC_REGISTRY
    search_paths = []
    if path:
        search_paths.append(path)
    env_path = os.getenv("MOCK_APAAR_REGISTRY_PATH")
    if env_path:
        search_paths.append(env_path)

    _here = os.path.dirname(os.path.abspath(__file__))
    search_paths.extend([
        os.path.join(_here, "..", "..", "sample_data", "mock_apaar_directory.json"),
        os.path.join(_here, "..", "..", "..", "sample_data", "mock_apaar_directory.json"),
        os.path.join(os.getcwd(), "sample_data", "mock_apaar_directory.json"),
    ])

    for p in search_paths:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        SYNTHETIC_REGISTRY.update(data)
                        logger.info(f"Loaded {len(data)} synthetic APAAR records from {p}")
                        return len(data)
            except Exception as e:
                logger.warning(f"Error loading synthetic APAAR registry from {p}: {e}")
    return len(SYNTHETIC_REGISTRY)


# Try automatic load on import if file exists
load_synthetic_registry()


# ---------------------------------------------------------------------------
# Abstract Identity Provider Interface
# ---------------------------------------------------------------------------

class IdentityProvider(ABC):
    @property
    @abstractmethod
    def source(self) -> str:
        """Identifier of the identity provider adapter."""
        pass

    @abstractmethod
    async def verify(
        self,
        request_id: str,
        apaar_id: Optional[str],
        student_name: str,
        date_of_birth: Union[str, date],
        consent_reference: Optional[str] = None,
    ) -> IdentityCheckResult:
        """Performs student identity verification."""
        pass


# ---------------------------------------------------------------------------
# Mock APAAR Implementation (MOCK_APAAR_V1)
# ---------------------------------------------------------------------------

class MockApaarProvider(IdentityProvider):
    @property
    def source(self) -> str:
        return SOURCE_MOCK_APAAR

    async def verify(
        self,
        request_id: str,
        apaar_id: Optional[str],
        student_name: str,
        date_of_birth: Union[str, date],
        consent_reference: Optional[str] = None,
    ) -> IdentityCheckResult:
        check_id = str(uuid.uuid4())
        checked_at = datetime.now(timezone.utc).isoformat()

        masked = mask_apaar(apaar_id)
        logger.info(
            f"[{SOURCE_MOCK_APAAR}] verify request={request_id} check={check_id} apaar={masked}"
        )

        # 1. APAAR missing -> NOT_PROVIDED
        if not apaar_id or not str(apaar_id).strip():
            return IdentityCheckResult(
                check_id=check_id,
                request_id=request_id,
                source=SOURCE_MOCK_APAAR,
                status=STATUS_NOT_PROVIDED,
                exists=None,
                name_match=None,
                dob_match=None,
                checked_at=checked_at,
                reason_code=REASON_NOT_PROVIDED,
                raw_details={"info": "APAAR identifier was not provided at time of inquiry"},
            )

        clean_apaar = re.sub(r"[\s\-]+", "", str(apaar_id).strip())

        # 2. Check Magic IDs / Env Toggles for TIMEOUT (UNAVAILABLE) and PENDING
        env_forced_status = os.getenv("MOCK_APAAR_FORCE_STATUS", "").upper()
        if env_forced_status == STATUS_UNAVAILABLE or clean_apaar.startswith("000000") or clean_apaar.endswith("999"):
            return IdentityCheckResult(
                check_id=check_id,
                request_id=request_id,
                source=SOURCE_MOCK_APAAR,
                status=STATUS_UNAVAILABLE,
                exists=None,
                name_match=None,
                dob_match=None,
                checked_at=checked_at,
                reason_code=REASON_TIMEOUT,
                raw_details={"error": "Simulated upstream APAAR gateway timeout (504)", "simulated": True},
            )

        if env_forced_status == STATUS_PENDING or clean_apaar.startswith("777777") or clean_apaar.endswith("888"):
            return IdentityCheckResult(
                check_id=check_id,
                request_id=request_id,
                source=SOURCE_MOCK_APAAR,
                status=STATUS_PENDING,
                exists=None,
                name_match=None,
                dob_match=None,
                checked_at=checked_at,
                reason_code=REASON_PENDING,
                raw_details={"info": "Simulated asynchronous registry processing in progress", "simulated": True},
            )

        # 3. Bad Format / Checksum -> FAILED(FORMAT)
        if not validate_apaar_format_and_checksum(clean_apaar) and clean_apaar not in SYNTHETIC_REGISTRY:
            return IdentityCheckResult(
                check_id=check_id,
                request_id=request_id,
                source=SOURCE_MOCK_APAAR,
                status=STATUS_FAILED,
                exists=False,
                name_match=None,
                dob_match=None,
                checked_at=checked_at,
                reason_code=REASON_FORMAT,
                raw_details={"error": "APAAR failed format or Luhn checksum validation"},
            )

        # 4. Check Registry -> Not in registry -> FAILED(NOT_FOUND)
        registry_record = SYNTHETIC_REGISTRY.get(clean_apaar)
        if not registry_record:
            return IdentityCheckResult(
                check_id=check_id,
                request_id=request_id,
                source=SOURCE_MOCK_APAAR,
                status=STATUS_FAILED,
                exists=False,
                name_match=None,
                dob_match=None,
                checked_at=checked_at,
                reason_code=REASON_NOT_FOUND,
                raw_details={"error": "APAAR not found in simulated national directory"},
            )

        # 5. In registry -> check name & dob matching
        name_matched = check_name_similarity(student_name, registry_record["name"])
        dob_matched = check_dob_match(date_of_birth, registry_record["dob"])

        if name_matched and dob_matched:
            return IdentityCheckResult(
                check_id=check_id,
                request_id=request_id,
                source=SOURCE_MOCK_APAAR,
                status=STATUS_PASSED,
                exists=True,
                name_match=True,
                dob_match=True,
                checked_at=checked_at,
                reason_code=REASON_MATCH_CONFIRMED,
                raw_details={"gender": registry_record.get("gender"), "simulated": True},
            )

        # In registry but mismatch -> FAILED(MISMATCH) with per-field booleans
        return IdentityCheckResult(
            check_id=check_id,
            request_id=request_id,
            source=SOURCE_MOCK_APAAR,
            status=STATUS_FAILED,
            exists=True,
            name_match=name_matched,
            dob_match=dob_matched,
            checked_at=checked_at,
            reason_code=REASON_MISMATCH,
            raw_details={
                "name_match": name_matched,
                "dob_match": dob_matched,
                "simulated": True,
            },
        )


# ---------------------------------------------------------------------------
# Provider Factory (Configurable via IDENTITY_PROVIDER_TYPE)
# ---------------------------------------------------------------------------

def get_identity_provider() -> IdentityProvider:
    """
    Factory returning the configured identity provider.
    Defaults to MockApaarProvider ('MOCK_APAAR_V1'). Allows future swapping.
    """
    provider_name = os.getenv("IDENTITY_PROVIDER_TYPE", SOURCE_MOCK_APAAR)
    if provider_name == SOURCE_MOCK_APAAR:
        return MockApaarProvider()
    # Real provider placeholder or fallback
    return MockApaarProvider()


# ---------------------------------------------------------------------------
# Retry Simulator (Exponential Backoff for UNAVAILABLE)
# ---------------------------------------------------------------------------

async def verify_with_retry(
    provider: IdentityProvider,
    request_id: str,
    apaar_id: Optional[str],
    student_name: str,
    date_of_birth: Union[str, date],
    consent_reference: Optional[str] = None,
    max_retries: int = 3,
    initial_delay: float = 0.02,
    backoff_multiplier: float = 2.0,
) -> Tuple[IdentityCheckResult, int]:
    """
    Executes identity check with exponential backoff on UNAVAILABLE.
    Returns (IdentityCheckResult, attempts_count).
    If still UNAVAILABLE after max_retries, stays PROVISIONAL (never fails).
    """
    attempts = 0
    delay = initial_delay
    last_result = None

    while attempts < max_retries:
        attempts += 1
        res = await provider.verify(
            request_id=request_id,
            apaar_id=apaar_id,
            student_name=student_name,
            date_of_birth=date_of_birth,
            consent_reference=consent_reference,
        )
        last_result = res
        if res.status != STATUS_UNAVAILABLE:
            return res, attempts
        if attempts < max_retries:
            await asyncio.sleep(delay)
            delay *= backoff_multiplier

    return last_result, attempts


# ---------------------------------------------------------------------------
# Policy Engine (Grace Period & UNAVAILABLE Provisional Guarantee)
# ---------------------------------------------------------------------------

DEFAULT_GRACE_PERIOD_DAYS = int(os.getenv("APAAR_NOT_PROVIDED_GRACE_DAYS", "30"))


def evaluate_identity_policy(
    identity_status: str,
    admission_date: Optional[datetime] = None,
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
) -> Dict[str, Any]:
    """
    Policy engine rules:
    - NOT_PROVIDED: allowed as PROVISIONAL for N days, then escalates to an Error.
    - UNAVAILABLE: never marks the record failed or verified (stays PROVISIONAL).
    - PASSED: Identity confirmed.
    - FAILED: Identity validation failed.
    """
    now = datetime.now(timezone.utc)
    if admission_date is not None:
        if getattr(admission_date, "tzinfo", None) is None:
            admit_time = admission_date.replace(tzinfo=timezone.utc)
        else:
            admit_time = admission_date
    else:
        admit_time = now
    days_elapsed = (now - admit_time).days if admit_time <= now else 0


    if identity_status == STATUS_PASSED:
        return {
            "lifecycle_status": "PROVISIONAL",
            "identity_resolution": "PASSED",
            "is_compliant": True,
            "escalated_error": False,
            "reason": "Identity successfully verified via simulated APAAR adapter",
        }

    if identity_status == STATUS_NOT_PROVIDED:
        if days_elapsed <= grace_period_days:
            remaining = grace_period_days - days_elapsed
            return {
                "lifecycle_status": "PROVISIONAL",
                "identity_resolution": "GRACE_PERIOD_ACTIVE",
                "is_compliant": True,
                "escalated_error": False,
                "days_elapsed": days_elapsed,
                "grace_days_remaining": remaining,
                "reason": f"APAAR missing. Active {grace_period_days}-day grace period ({remaining} days remaining).",
            }
        else:
            return {
                "lifecycle_status": "ERROR",
                "identity_resolution": "GRACE_PERIOD_EXPIRED",
                "is_compliant": False,
                "escalated_error": True,
                "days_elapsed": days_elapsed,
                "grace_days_remaining": 0,
                "reason": f"APAAR missing. Allowed {grace_period_days}-day grace period expired.",
            }

    if identity_status == STATUS_UNAVAILABLE:
        # Rule 5: UNAVAILABLE never marks the record failed or verified
        return {
            "lifecycle_status": "PROVISIONAL",
            "identity_resolution": "RETRY_QUEUED",
            "is_compliant": True,
            "escalated_error": False,
            "reason": "Upstream APAAR service unavailable (timeout). Record stays provisional.",
        }

    if identity_status == STATUS_PENDING:
        return {
            "lifecycle_status": "PROVISIONAL",
            "identity_resolution": "PENDING_ASYNCHRONOUS",
            "is_compliant": True,
            "escalated_error": False,
            "reason": "Identity verification request queued in background.",
        }

    # STATUS_FAILED
    return {
        "lifecycle_status": "PROVISIONAL",
        "identity_resolution": "FAILED",
        "is_compliant": False,
        "escalated_error": True,
        "reason": "Identity verification check failed.",
    }
