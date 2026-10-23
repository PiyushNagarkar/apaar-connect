"""
Duplicate Detection Service (backend/services/duplicate_detection.py)

A candidate generator plus scorer (not a fraud classifier).
Implements:
1. Normalisation:
   - Name: lowercase, strip honorifics/punctuation/extra spaces, transliteration-tolerant.
   - DOB: ISO YYYY-MM-DD.
   - Mobile: last 10 digits.
   - Email: lowercase.
2. Tiers (returns match_type, score 0-1, reasons[]):
   - CRITICAL: same apaar_hash active (CONFIRMED/ACTIVE/PROVISIONAL) across two different institutions.
   - HIGH: same apaar_hash twice within one institution or one batch.
   - MEDIUM: same normalised name + DOB + mobile_last10 (no APAAR match).
   - FUZZY: name similarity only (Jaro-Winkler >= 0.92 AND same DOB).
            CRITICAL: Name-only similarity with a different DOB produces NO alert!
   - PROGRESSION: same apaar_hash but earlier enrollment is COMPLETED -> logged as normal progression, no case.
3. Candidate blocking:
   - Index/lookup blocking on dob, mobile_last10/mobile_hash, apaar_hash so matching is O(candidates), not O(n^2).
   - Weighted feature scorer:
     score = 0.5*apaar_exact + 0.2*dob_equal + 0.15*mobile_equal + 0.15*name_similarity (configurable).
   - ALWAYS returns the matched fields as reason codes.
4. Policy:
   - Matches above threshold create a duplicate_candidates row and a review case.
   - Nothing is auto-merged, deleted or rejected.
   - Same-institution exact matches may block the second row's commit and put both into DUPLICATE / UNDER_REVIEW.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import unicodedata

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.audit import AuditEvent
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.student import Student
from backend.security.crypto import compute_apaar_hash

logger = logging.getLogger("duplicate_detection")

# ---------------------------------------------------------------------------
# Tier & Reason Constants
# ---------------------------------------------------------------------------
TIER_CRITICAL = "CRITICAL"
TIER_HIGH = "HIGH"
TIER_MEDIUM = "MEDIUM"
TIER_FUZZY = "FUZZY"
TIER_PROGRESSION = "PROGRESSION"

ALL_TIERS = {TIER_CRITICAL, TIER_HIGH, TIER_MEDIUM, TIER_FUZZY, TIER_PROGRESSION}

REASON_APAAR_EXACT = "APAAR_EXACT_MATCH"
REASON_DOB_EXACT = "DOB_EXACT_MATCH"
REASON_MOBILE_EXACT = "MOBILE_EXACT_MATCH"
REASON_NAME_EXACT = "NAME_EXACT_MATCH"
REASON_NAME_SIMILARITY = "NAME_SIMILARITY_MATCH"
REASON_CROSS_INSTITUTION_ACTIVE = "CROSS_INSTITUTION_ACTIVE"
REASON_SAME_INSTITUTION_DUPLICATE = "SAME_INSTITUTION_DUPLICATE"
REASON_DEMOGRAPHIC_EXACT = "DEMOGRAPHIC_EXACT_MATCH"
REASON_FUZZY_NAME_DOB = "FUZZY_NAME_DOB_MATCH"
REASON_NORMAL_PROGRESSION = "NORMAL_ACADEMIC_PROGRESSION"
REASON_COMPLETED_PRIOR = "COMPLETED_PRIOR_ENROLLMENT"

# Honorifics stripped during normalization
HONORIFICS = [
    "mr", "ms", "mrs", "miss", "shri", "shree", "smt", "shrimati",
    "dr", "prof", "master", "kumar", "kumari", "er", "ca",
]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class ScorerWeights:
    apaar_weight: float = 0.50
    dob_weight: float = 0.20
    mobile_weight: float = 0.15
    name_weight: float = 0.15

    def compute(self, apaar_exact: bool, dob_equal: bool, mobile_equal: bool, name_similarity: float) -> float:
        s = (
            (self.apaar_weight if apaar_exact else 0.0)
            + (self.dob_weight if dob_equal else 0.0)
            + (self.mobile_weight if mobile_equal else 0.0)
            + (self.name_weight * max(0.0, min(1.0, name_similarity)))
        )
        return round(s, 4)


@dataclass
class DuplicateMatchResult:
    match_type: str
    score: float
    reasons: List[str]
    enrollment_a_id: Optional[str] = None
    enrollment_b_id: Optional[str] = None
    student_a_id: Optional[str] = None
    student_b_id: Optional[str] = None
    requires_case: bool = True
    is_progression: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normalization Functions
# ---------------------------------------------------------------------------
def normalize_name_dedup(name: Optional[str]) -> str:
    """
    Normalises name:
    - Unicode NFKD decomposition
    - Strips accents/diacritics
    - Lowercase
    - Strips honorifics (mr, ms, mrs, shri, smt, dr, prof, etc.)
    - Strips punctuation and digits
    - Collapses extra spaces
    """
    if not name:
        return ""
    # Unicode NFKD & diacritics removal
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()

    # Strip punctuation and special characters
    text = re.sub(r"[^\w\s]", " ", text)

    # Strip honorifics as standalone words
    for h in HONORIFICS:
        text = re.sub(r"\b" + re.escape(h) + r"\b", " ", text)

    # Remove digits and collapse whitespace
    text = re.sub(r"\d+", " ", text)
    return " ".join(text.split())


def normalize_transliteration(name: str) -> str:
    """
    Transliteration folding for common Indian English phonetic variations:
    - w -> v
    - ee -> i, oo -> u
    - au -> o, ai -> e
    - double consonants -> single consonant (e.g. tt -> t, ll -> l, gg -> g)
    - sh -> s, ch -> c, th -> t, ph -> f
    """
    s = normalize_name_dedup(name)
    s = s.replace("w", "v")
    s = s.replace("ee", "i").replace("oo", "u")
    s = s.replace("au", "o").replace("ai", "e")
    s = re.sub(r"([a-z])\1+", r"\1", s)
    s = s.replace("sh", "s").replace("ch", "c").replace("th", "t").replace("ph", "f")
    return s


def normalize_dob_iso(dob_input: Any) -> Optional[str]:
    """Normalises date of birth to ISO string YYYY-MM-DD."""
    if not dob_input:
        return None
    if isinstance(dob_input, (datetime, date)):
        return dob_input.strftime("%Y-%m-%d")

    cleaned = str(dob_input).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Attempt to extract YYYY-MM-DD prefix
    if re.match(r"^\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned[:10]
    return cleaned or None


def normalize_mobile_10(mobile_input: Any) -> Optional[str]:
    """Strips non-digits and extracts last 10 digits."""
    if not mobile_input:
        return None
    digits = re.sub(r"\D", "", str(mobile_input))
    if len(digits) >= 10:
        return digits[-10:]
    return None


def normalize_email(email_input: Any) -> Optional[str]:
    """Lowercases and trims email address."""
    if not email_input:
        return None
    return str(email_input).strip().lower()


def compute_mobile_hash(mobile_10: Optional[str]) -> Optional[str]:
    """Computes SHA-256 hash of last 10 digits for blind index lookup."""
    if not mobile_10:
        return None
    return hashlib.sha256(mobile_10.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Jaro-Winkler Similarity Metric
# ---------------------------------------------------------------------------
def jaro_similarity(s1: str, s2: str) -> float:
    """Computes standard Jaro distance between two strings."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_window = max(len1, len2) // 2 - 1
    if match_window < 0:
        match_window = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    for i in range(len1):
        start = max(0, i - match_window)
        end = min(i + match_window + 1, len2)
        for j in range(start, end):
            if not s2_matches[j] and s1[i] == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    transpositions = 0
    k = 0
    for i in range(len1):
        if s1_matches[i]:
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    transpositions //= 2
    return ((matches / len1) + (matches / len2) + ((matches - transpositions) / matches)) / 3.0


def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1, max_l: int = 4) -> float:
    """Computes Jaro-Winkler distance with prefix scaling factor p."""
    j = jaro_similarity(s1, s2)
    l = 0
    for c1, c2 in zip(s1, s2):
        if c1 == c2:
            l += 1
            if l == max_l:
                break
        else:
            break
    return j + (l * p * (1.0 - j))


def calculate_name_similarity(name1: Optional[str], name2: Optional[str]) -> float:
    """
    Computes robust transliteration-tolerant, word-order-tolerant name similarity.
    Evaluates:
    1. Direct string Jaro-Winkler
    2. Sorted-token Jaro-Winkler (handles token order permutation like 'Aarav Sharma' vs 'Sharma Aarav')
    3. Transliteration-folded Jaro-Winkler
    Returns the maximum similarity in [0.0, 1.0].
    """
    n1 = normalize_name_dedup(name1)
    n2 = normalize_name_dedup(name2)
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0

    tokens1 = n1.split()
    tokens2 = n2.split()
    if set(tokens1) == set(tokens2):
        return 1.0

    # Sorted tokens
    sorted1 = " ".join(sorted(tokens1))
    sorted2 = " ".join(sorted(tokens2))

    # Transliteration fold
    t1 = normalize_transliteration(n1)
    t2 = normalize_transliteration(n2)

    jw_raw = jaro_winkler_similarity(n1, n2)
    jw_sorted = jaro_winkler_similarity(sorted1, sorted2)
    jw_trans = jaro_winkler_similarity(t1, t2)

    return max(jw_raw, jw_sorted, jw_trans)


# ---------------------------------------------------------------------------
# Candidate Generator with Index Blocking
# ---------------------------------------------------------------------------
def find_candidate_enrollments(
    db: Session,
    apaar_hash: Optional[str] = None,
    dob_iso: Optional[str] = None,
    mobile_10: Optional[str] = None,
    name_norm: Optional[str] = None,
    exclude_enrollment_id: Optional[str] = None,
    institution_id: Optional[str] = None,
    limit: int = 200,
) -> List[Enrollment]:
    """
    Candidate Blocking:
    Queries database for candidates sharing at least ONE blocking key:
    - Same apaar_hash
    - Same date of birth (DOB)
    - Same mobile_hash or mobile_last4
    Matching is O(candidates) rather than scanning all database rows O(n^2).
    """
    filters = []

    if apaar_hash and apaar_hash.strip():
        filters.append(Student.apaar_hash == apaar_hash.strip())

    parsed_dob = None
    if dob_iso:
        try:
            parsed_dob = datetime.strptime(dob_iso, "%Y-%m-%d").date()
            filters.append(Student.dob == parsed_dob)
        except Exception:
            pass

    if mobile_10 and len(mobile_10) >= 10:
        m_hash = compute_mobile_hash(mobile_10)
        m_last4 = mobile_10[-4:]
        filters.append(Student.mobile_hash == m_hash)
        filters.append(Student.mobile_last4 == m_last4)

    if not filters:
        # If no blocking keys are provided, return empty candidate list
        return []

    query = (
        db.query(Enrollment)
        .join(Student, Enrollment.student_id == Student.id)
        .filter(or_(*filters))
    )

    if exclude_enrollment_id:
        query = query.filter(Enrollment.id != exclude_enrollment_id)

    # Exclude withdrawn / cancelled from creating new active conflicts
    # but keep COMPLETED for progression checks
    query = query.filter(Enrollment.status.notin_(["WITHDRAWN", "CANCELLED", "REJECTED"]))

    return query.limit(limit).all()


# ---------------------------------------------------------------------------
# Scorer and Tier Classifier
# ---------------------------------------------------------------------------
def score_and_classify_pair(
    record_a: Dict[str, Any],
    record_b: Dict[str, Any],
    weights: Optional[ScorerWeights] = None,
    threshold: float = 0.32,
) -> Optional[DuplicateMatchResult]:
    """
    Evaluates two admission/student records, computes weighted feature score,
    and assigns a tier:
    1. CRITICAL: same apaar_hash active (CONFIRMED/ACTIVE/PROVISIONAL) across two different institutions.
    2. HIGH: same apaar_hash twice within one institution or one batch.
    3. MEDIUM: same normalised name + DOB + mobile_last10 (no APAAR match).
    4. FUZZY: name similarity only (Jaro-Winkler >= 0.92 AND same DOB).
       *CRITICAL*: Name-only similarity with a different DOB produces NO alert!
    5. PROGRESSION: same apaar_hash but earlier enrollment is COMPLETED -> logged as normal progression, no case.
    """
    if weights is None:
        weights = ScorerWeights()

    # 1. Extract and normalize fields for Record A
    apaar_a = record_a.get("apaar_hash") or (compute_apaar_hash(record_a.get("apaar_id")) if record_a.get("apaar_id") else None)
    name_a = normalize_name_dedup(record_a.get("name") or record_a.get("name_normalized"))
    dob_a = normalize_dob_iso(record_a.get("dob"))
    mobile_a = normalize_mobile_10(record_a.get("mobile") or record_a.get("mobile_10"))
    inst_a = str(record_a.get("institution_id") or "")
    status_a = str(record_a.get("status") or "ACTIVE").upper()

    # 2. Extract and normalize fields for Record B
    apaar_b = record_b.get("apaar_hash") or (compute_apaar_hash(record_b.get("apaar_id")) if record_b.get("apaar_id") else None)
    name_b = normalize_name_dedup(record_b.get("name") or record_b.get("name_normalized"))
    dob_b = normalize_dob_iso(record_b.get("dob"))
    mobile_b = normalize_mobile_10(record_b.get("mobile") or record_b.get("mobile_10"))
    inst_b = str(record_b.get("institution_id") or "")
    status_b = str(record_b.get("status") or "ACTIVE").upper()

    # 3. Compute component matches
    apaar_exact = bool(apaar_a and apaar_b and apaar_a == apaar_b)
    dob_equal = bool(dob_a and dob_b and dob_a == dob_b)
    mobile_equal = bool(mobile_a and mobile_b and mobile_a == mobile_b)
    name_similarity = calculate_name_similarity(name_a, name_b)

    # 4. Reason codes collection
    reasons: List[str] = []
    if apaar_exact:
        reasons.append(REASON_APAAR_EXACT)
    if dob_equal:
        reasons.append(REASON_DOB_EXACT)
    if mobile_equal:
        reasons.append(REASON_MOBILE_EXACT)
    if name_similarity >= 0.99:
        reasons.append(REASON_NAME_EXACT)
    elif name_similarity >= 0.92:
        reasons.append(REASON_NAME_SIMILARITY)

    score = weights.compute(apaar_exact, dob_equal, mobile_equal, name_similarity)

    # -----------------------------------------------------------------------
    # Tier 5: PROGRESSION
    # Same apaar_hash but earlier enrollment is COMPLETED -> logged as normal progression, no case.
    # -----------------------------------------------------------------------
    if apaar_exact and (status_a == "COMPLETED" or status_b == "COMPLETED"):
        prog_reasons = list(reasons)
        prog_reasons.append(REASON_COMPLETED_PRIOR)
        prog_reasons.append(REASON_NORMAL_PROGRESSION)
        return DuplicateMatchResult(
            match_type=TIER_PROGRESSION,
            score=score,
            reasons=prog_reasons,
            enrollment_a_id=record_a.get("enrollment_id"),
            enrollment_b_id=record_b.get("enrollment_id"),
            student_a_id=record_a.get("student_id"),
            student_b_id=record_b.get("student_id"),
            requires_case=False,
            is_progression=True,
            details={
                "explanation": "Earlier enrollment is COMPLETED. Logged as valid academic progression.",
                "institution_a": inst_a,
                "institution_b": inst_b,
                "status_a": status_a,
                "status_b": status_b,
            },
        )

    # -----------------------------------------------------------------------
    # Tier 1: CRITICAL
    # Same apaar_hash active (CONFIRMED/ACTIVE/PROVISIONAL) in two different institutions.
    # -----------------------------------------------------------------------
    if apaar_exact and inst_a and inst_b and (inst_a != inst_b):
        crit_reasons = list(reasons)
        crit_reasons.append(REASON_CROSS_INSTITUTION_ACTIVE)
        return DuplicateMatchResult(
            match_type=TIER_CRITICAL,
            score=max(score, 0.90),
            reasons=crit_reasons,
            enrollment_a_id=record_a.get("enrollment_id"),
            enrollment_b_id=record_b.get("enrollment_id"),
            student_a_id=record_a.get("student_id"),
            student_b_id=record_b.get("student_id"),
            requires_case=True,
            is_progression=False,
            details={
                "explanation": f"Same APAAR hash is actively enrolled in two different institutions: '{inst_a}' and '{inst_b}'.",
                "institution_a": inst_a,
                "institution_b": inst_b,
                "status_a": status_a,
                "status_b": status_b,
            },
        )

    # -----------------------------------------------------------------------
    # Tier 2: HIGH
    # Same apaar_hash twice within one institution or one batch.
    # -----------------------------------------------------------------------
    if apaar_exact:
        high_reasons = list(reasons)
        high_reasons.append(REASON_SAME_INSTITUTION_DUPLICATE)
        return DuplicateMatchResult(
            match_type=TIER_HIGH,
            score=max(score, 0.85),
            reasons=high_reasons,
            enrollment_a_id=record_a.get("enrollment_id"),
            enrollment_b_id=record_b.get("enrollment_id"),
            student_a_id=record_a.get("student_id"),
            student_b_id=record_b.get("student_id"),
            requires_case=True,
            is_progression=False,
            details={
                "explanation": f"Duplicate APAAR hash detected within the same institution or submission batch ('{inst_a}').",
                "institution_a": inst_a,
                "institution_b": inst_b,
                "status_a": status_a,
                "status_b": status_b,
            },
        )

    # -----------------------------------------------------------------------
    # Tier 3: MEDIUM
    # Same normalised name + DOB + mobile_last10 (no APAAR match).
    # -----------------------------------------------------------------------
    name_exact_or_equiv = (name_a == name_b) or (name_similarity >= 0.99)
    if (not apaar_exact) and name_exact_or_equiv and dob_equal and mobile_equal:
        med_reasons = list(reasons)
        med_reasons.append(REASON_DEMOGRAPHIC_EXACT)
        return DuplicateMatchResult(
            match_type=TIER_MEDIUM,
            score=max(score, 0.50),
            reasons=med_reasons,
            enrollment_a_id=record_a.get("enrollment_id"),
            enrollment_b_id=record_b.get("enrollment_id"),
            student_a_id=record_a.get("student_id"),
            student_b_id=record_b.get("student_id"),
            requires_case=True,
            is_progression=False,
            details={
                "explanation": "Identical demographic triad (normalised name, DOB, and 10-digit mobile) without APAAR link.",
                "institution_a": inst_a,
                "institution_b": inst_b,
            },
        )

    # -----------------------------------------------------------------------
    # Tier 4: FUZZY
    # Name similarity only (Jaro-Winkler >= 0.92 AND same DOB).
    # *CRITICAL RULE*: Name-only similarity with a different DOB produces NO alert!
    # -----------------------------------------------------------------------
    if name_similarity >= 0.92:
        if not dob_equal:
            # Different DOB produces NO alert (e.g. common names or twins with different DOB)
            return None

        # Same DOB with fuzzy name match
        fuzzy_reasons = list(reasons)
        fuzzy_reasons.append(REASON_FUZZY_NAME_DOB)
        return DuplicateMatchResult(
            match_type=TIER_FUZZY,
            score=score,
            reasons=fuzzy_reasons,
            enrollment_a_id=record_a.get("enrollment_id"),
            enrollment_b_id=record_b.get("enrollment_id"),
            student_a_id=record_a.get("student_id"),
            student_b_id=record_b.get("student_id"),
            requires_case=True,
            is_progression=False,
            details={
                "explanation": f"High name similarity ({name_similarity:.4f} >= 0.92) with identical Date of Birth.",
                "name_similarity": round(name_similarity, 4),
                "institution_a": inst_a,
                "institution_b": inst_b,
            },
        )

    # If none of the 5 explicit tiers are satisfied, it is not a duplicate candidate
    return None


# ---------------------------------------------------------------------------
# Core Service Orchestrator
# ---------------------------------------------------------------------------
class DuplicateDetectionService:
    def __init__(self, db: Session, weights: Optional[ScorerWeights] = None):
        self.db = db
        self.weights = weights or ScorerWeights()

    def check_record(
        self,
        record: Dict[str, Any],
        exclude_enrollment_id: Optional[str] = None,
        save_candidates: bool = False,
        actor_id: Optional[str] = None,
    ) -> List[DuplicateMatchResult]:
        """
        Runs candidate blocking and scoring for an incoming student/enrollment record.
        Optionally persists DuplicateCandidate and ReviewCase entities.
        """
        apaar_hash = record.get("apaar_hash") or (compute_apaar_hash(record.get("apaar_id")) if record.get("apaar_id") else None)
        dob_iso = normalize_dob_iso(record.get("dob"))
        mobile_10 = normalize_mobile_10(record.get("mobile"))
        name_norm = normalize_name_dedup(record.get("name"))

        candidates = find_candidate_enrollments(
            db=self.db,
            apaar_hash=apaar_hash,
            dob_iso=dob_iso,
            mobile_10=mobile_10,
            name_norm=name_norm,
            exclude_enrollment_id=exclude_enrollment_id,
            institution_id=record.get("institution_id"),
        )

        results: List[DuplicateMatchResult] = []
        for cand in candidates:
            cand_student = cand.student
            cand_record = {
                "enrollment_id": str(cand.id),
                "student_id": str(cand_student.id) if cand_student else None,
                "apaar_hash": cand_student.apaar_hash if cand_student else None,
                "name": cand_student.name if cand_student else "",
                "name_normalized": cand_student.name_normalized if cand_student else "",
                "dob": cand_student.dob.strftime("%Y-%m-%d") if (cand_student and cand_student.dob) else None,
                "mobile": cand_student.mobile_last4 if cand_student else None,
                "institution_id": str(cand.institution_id),
                "status": str(cand.status),
            }

            match_res = score_and_classify_pair(
                record_a=cand_record,
                record_b=record,
                weights=self.weights,
            )

            if match_res:
                match_res.enrollment_a_id = cand_record["enrollment_id"]
                match_res.enrollment_b_id = record.get("enrollment_id")
                match_res.student_a_id = cand_record["student_id"]
                match_res.student_b_id = record.get("student_id")
                results.append(match_res)

                if save_candidates and record.get("enrollment_id"):
                    self._persist_match(match_res, actor_id=actor_id)

        return results

    def check_enrollment(
        self,
        enrollment_id: str,
        save_candidates: bool = True,
        actor_id: Optional[str] = None,
    ) -> List[DuplicateMatchResult]:
        """Loads an existing enrollment and checks it against all other active enrollments."""
        enrollment = self.db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
        if not enrollment:
            return []

        student = enrollment.student
        record = {
            "enrollment_id": str(enrollment.id),
            "student_id": str(student.id) if student else None,
            "apaar_hash": student.apaar_hash if student else None,
            "name": student.name if student else "",
            "name_normalized": student.name_normalized if student else "",
            "dob": student.dob.strftime("%Y-%m-%d") if (student and student.dob) else None,
            "mobile": student.mobile_last4 if student else None,
            "institution_id": str(enrollment.institution_id),
            "status": str(enrollment.status),
        }

        return self.check_record(
            record=record,
            exclude_enrollment_id=str(enrollment.id),
            save_candidates=save_candidates,
            actor_id=actor_id,
        )

    def _persist_match(
        self,
        match: DuplicateMatchResult,
        actor_id: Optional[str] = None,
    ) -> Optional[DuplicateCandidate]:
        """
        Persists DuplicateCandidate and opens ReviewCase.
        Policy:
        - Nothing is auto-merged, deleted, or rejected.
        - Same-institution exact matches put both into UNDER_REVIEW / DUPLICATE.
        - Progression is logged without opening a review case.
        """
        if not match.enrollment_a_id or not match.enrollment_b_id:
            return None

        # Check if already recorded
        existing = (
            self.db.query(DuplicateCandidate)
            .filter(
                or_(
                    (DuplicateCandidate.enrollment_a == match.enrollment_a_id) & (DuplicateCandidate.enrollment_b == match.enrollment_b_id),
                    (DuplicateCandidate.enrollment_a == match.enrollment_b_id) & (DuplicateCandidate.enrollment_b == match.enrollment_a_id),
                )
            )
            .first()
        )

        status_str = "LOGGED_PROGRESSION" if match.is_progression else "DETECTED"
        if not existing:
            candidate_obj = DuplicateCandidate(
                enrollment_a=match.enrollment_a_id,
                enrollment_b=match.enrollment_b_id,
                match_type=match.match_type,
                score=match.score,
                reasons=match.reasons,
                status=status_str,
            )
            self.db.add(candidate_obj)
            self.db.flush()
        else:
            candidate_obj = existing
            candidate_obj.match_type = match.match_type
            candidate_obj.score = match.score
            candidate_obj.reasons = match.reasons
            self.db.flush()

        # Progression logs normally; no case created
        if match.is_progression or not match.requires_case:
            return candidate_obj

        # Priority mapping (Rule 6)
        priority_map = {
            TIER_CRITICAL: 95.0,
            TIER_HIGH: 85.0,
            TIER_MEDIUM: 65.0,
            TIER_FUZZY: 50.0,
        }
        severity_map = {
            TIER_CRITICAL: "CRITICAL",
            TIER_HIGH: "HIGH",
            TIER_MEDIUM: "MEDIUM",
            TIER_FUZZY: "LOW",
        }

        prio = priority_map.get(match.match_type, 60.0)
        sev = severity_map.get(match.match_type, "MEDIUM")

        # Check existing review case
        existing_case = (
            self.db.query(ReviewCase)
            .filter(
                ReviewCase.enrollment_id == match.enrollment_b_id,
                ReviewCase.type == "DUPLICATE_MATCH",
            )
            .first()
        )

        if not existing_case:
            case = ReviewCase(
                type="DUPLICATE_MATCH",
                severity=sev,
                priority=prio,
                enrollment_id=match.enrollment_b_id,
                status="OPEN",
                evidence={
                    "candidate_id": str(candidate_obj.id),
                    "enrollment_a": match.enrollment_a_id,
                    "enrollment_b": match.enrollment_b_id,
                    "match_type": match.match_type,
                    "score": match.score,
                    "reasons": match.reasons,
                    "details": match.details,
                },
            )
            self.db.add(case)
            self.db.flush()

        # Policy for HIGH / CRITICAL same-institution exact matches:
        # Mark enrollment as UNDER_REVIEW (does not auto-delete or auto-reject)
        if match.match_type in (TIER_CRITICAL, TIER_HIGH):
            enroll_b = self.db.query(Enrollment).filter(Enrollment.id == match.enrollment_b_id).first()
            if enroll_b and enroll_b.status not in ("UNDER_REVIEW", "WITHDRAWN"):
                enroll_b.status = "UNDER_REVIEW"
                enroll_b.verified = False

            if match.match_type == TIER_HIGH:
                enroll_a = self.db.query(Enrollment).filter(Enrollment.id == match.enrollment_a_id).first()
                if enroll_a and enroll_a.status not in ("UNDER_REVIEW", "WITHDRAWN"):
                    enroll_a.status = "UNDER_REVIEW"
                    enroll_a.verified = False

        return candidate_obj
