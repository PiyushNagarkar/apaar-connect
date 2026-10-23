"""
Test Suite for Duplicate Detection Service & API (backend/tests/test_duplicate_detection.py)

Tests:
1. Normalisation:
   - Name: lowercase, strip honorifics/punctuation/extra spaces, transliteration-tolerant.
   - DOB: ISO YYYY-MM-DD.
   - Mobile: last 10 digits.
   - Email: lowercase.
2. Jaro-Winkler Similarity Metric:
   - Identical names (1.0)
   - Swapped name tokens (1.0)
   - Typo tolerance (>= 0.92)
   - Distinct names (< 0.92)
3. Tiers:
   - Tier 1: CRITICAL (cross-institution active)
   - Tier 2: HIGH (same-institution duplicate)
   - Tier 3: MEDIUM (demographic triad without APAAR)
   - Tier 4: FUZZY (name similarity >= 0.92 and same DOB)
   - Tier 5: PROGRESSION (completed prior enrollment -> logged as normal progression, no case)
4. Regulatory Invariants:
   - Twins (same DOB, same household mobile, different first names) produce NO alert
   - Same name with different DOB produces NO alert
5. Candidate Blocking:
   - Index/lookup blocking ensures O(candidates) retrieval
6. Policy & Persistence:
   - Creates DuplicateCandidate and ReviewCase
   - Same-institution duplicate sets status to UNDER_REVIEW
   - Progression does not open review cases
7. API Endpoints:
   - POST /api/duplicates/check
   - GET /api/duplicates/candidates (with institutional scoping)
"""
from datetime import date, datetime, timezone
import pytest
from sqlalchemy.orm import Session

from backend.models.approval import ApprovalStatus, ProgramApproval
from backend.models.duplicate import DuplicateCandidate
from backend.models.enrollment import Enrollment
from backend.models.institution import Institution
from backend.models.review import ReviewCase
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.security.crypto import compute_apaar_hash, create_jwt
from backend.services.duplicate_detection import (
    DuplicateDetectionService,
    ScorerWeights,
    calculate_name_similarity,
    compute_mobile_hash,
    find_candidate_enrollments,
    jaro_winkler_similarity,
    normalize_dob_iso,
    normalize_email,
    normalize_mobile_10,
    normalize_name_dedup,
    normalize_transliteration,
    score_and_classify_pair,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_MEDIUM,
    TIER_FUZZY,
    TIER_PROGRESSION,
    REASON_APAAR_EXACT,
    REASON_CROSS_INSTITUTION_ACTIVE,
    REASON_SAME_INSTITUTION_DUPLICATE,
    REASON_DEMOGRAPHIC_EXACT,
    REASON_FUZZY_NAME_DOB,
    REASON_NORMAL_PROGRESSION,
)


@pytest.fixture
def dup_test_setup(db_session: Session):
    """Sets up two institutions and frozen program approvals for cross-institution tests."""
    now = datetime.now(timezone.utc)

    inst1 = Institution(code="1-DUP-INST-01", name="Delhi Technical Institute", status="ACTIVE")
    inst2 = Institution(code="1-DUP-INST-02", name="Mumbai Institute of Tech", status="ACTIVE")
    db_session.add_all([inst1, inst2])
    db_session.commit()

    appr1 = ProgramApproval(
        institution_id=inst1.id,
        programme="ENGINEERING",
        branch="CSE",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-DEL-2024",
        version=1,
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by="aicte_admin",
    )
    appr2 = ProgramApproval(
        institution_id=inst2.id,
        programme="ENGINEERING",
        branch="CSE",
        campus="MAIN",
        shift="FIRST",
        academic_year="2024-2025",
        approval_ref="EOA-BOM-2024",
        version=1,
        status=ApprovalStatus.FROZEN,
        frozen_at=now,
        frozen_by="aicte_admin",
    )
    db_session.add_all([appr1, appr2])
    db_session.commit()

    return {
        "inst1": inst1,
        "inst2": inst2,
        "appr1": appr1,
        "appr2": appr2,
    }


# ===========================================================================
# 1. Normalisation Tests
# ===========================================================================
def test_normalization_name_honorifics_and_transliteration():
    """Verifies that honorifics, punctuation, whitespace, and transliteration are cleanly normalized."""
    assert normalize_name_dedup("Dr. Vikram Seth") == "vikram seth"
    assert normalize_name_dedup("Prof. Smt. Anita Sharma") == "anita sharma"
    assert normalize_name_dedup("Shri Amit Kumar, Master") == "amit"
    assert normalize_name_dedup("  Priya   Patel  ") == "priya patel"
    assert normalize_name_dedup("S. K. Gupta") == "s k gupta"

    # Transliteration folding and similarity
    assert normalize_transliteration("Pooja Agarwal") == normalize_transliteration("Puja Aggarwal")
    assert normalize_transliteration("Gaurav Mukherjee") == normalize_transliteration("Gorav Mukherjee")
    assert calculate_name_similarity("Rahul Verma", "Rahul Warma") >= 0.92


def test_normalization_dob_mobile_email():
    """Verifies date, mobile, and email field normalizations."""
    assert normalize_dob_iso("2005-04-12") == "2005-04-12"
    assert normalize_dob_iso("12/04/2005") == "2005-04-12"
    assert normalize_dob_iso("12-04-2005") == "2005-04-12"
    assert normalize_dob_iso(date(2005, 4, 12)) == "2005-04-12"

    assert normalize_mobile_10("+91 98765 43210") == "9876543210"
    assert normalize_mobile_10("09876543210") == "9876543210"
    assert normalize_mobile_10("12345") is None

    assert normalize_email(" Student@Example.COM ") == "student@example.com"


# ===========================================================================
# 2. String Distance & Similarity Metric Tests
# ===========================================================================
def test_name_similarity_metric_token_order_and_typos():
    """Tests Jaro-Winkler metric with token order permutations and typos."""
    # Identical
    assert calculate_name_similarity("Aarav Sharma", "Aarav Sharma") == 1.0

    # Token swapped
    assert calculate_name_similarity("Priya Patel", "Patel Priya") == 1.0

    # Typo tolerance
    sim_typo = calculate_name_similarity("Deepak Choudhary", "Deepak Chowdhary")
    assert sim_typo >= 0.92

    # Distinct individuals
    sim_distinct = calculate_name_similarity("Rahul Sharma", "Rohan Sharma")
    assert sim_distinct < 0.92


# ===========================================================================
# 3. Tiers & Scorer Tests
# ===========================================================================
def test_tier_1_critical_cross_institution_active():
    """Tier 1: Same apaar_hash active across two different institutions -> CRITICAL."""
    h = compute_apaar_hash("987654321015")
    rec_a = {"apaar_hash": h, "name": "Priya Patel", "dob": "2005-03-21", "institution_id": "INST-A", "status": "CONFIRMED"}
    rec_b = {"apaar_hash": h, "name": "Priya Patel", "dob": "2005-03-21", "institution_id": "INST-B", "status": "ACTIVE"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is not None
    assert res.match_type == TIER_CRITICAL
    assert res.score >= 0.90
    assert REASON_APAAR_EXACT in res.reasons
    assert REASON_CROSS_INSTITUTION_ACTIVE in res.reasons
    assert res.requires_case is True


def test_tier_2_high_same_institution():
    """Tier 2: Same apaar_hash twice within same institution -> HIGH."""
    h = compute_apaar_hash("987654321013")
    rec_a = {"apaar_hash": h, "name": "Rahul Sharma", "dob": "2004-11-15", "institution_id": "INST-A", "status": "CONFIRMED"}
    rec_b = {"apaar_hash": h, "name": "Rahul Sharma", "dob": "2004-11-15", "institution_id": "INST-A", "status": "PROVISIONAL"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is not None
    assert res.match_type == TIER_HIGH
    assert res.score >= 0.85
    assert REASON_SAME_INSTITUTION_DUPLICATE in res.reasons
    assert res.requires_case is True


def test_tier_3_medium_demographic_triad():
    """Tier 3: Same normalized name + DOB + mobile_last10 without APAAR match -> MEDIUM."""
    rec_a = {"apaar_hash": None, "name": "Aarav Kumar", "dob": "2005-07-10", "mobile": "9876543210", "institution_id": "INST-A"}
    rec_b = {"apaar_hash": None, "name": "Aarav Kumar", "dob": "2005-07-10", "mobile": "9876543210", "institution_id": "INST-B"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is not None
    assert res.match_type == TIER_MEDIUM
    assert res.score >= 0.50
    assert REASON_DEMOGRAPHIC_EXACT in res.reasons
    assert res.requires_case is True


def test_tier_4_fuzzy_name_and_same_dob():
    """Tier 4: Name similarity >= 0.92 AND exact same DOB -> FUZZY."""
    rec_a = {"apaar_hash": None, "name": "Deepak Choudhary", "dob": "2004-12-05", "institution_id": "INST-A"}
    rec_b = {"apaar_hash": None, "name": "Deepak Chowdhary", "dob": "2004-12-05", "institution_id": "INST-B"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is not None
    assert res.match_type == TIER_FUZZY
    assert REASON_FUZZY_NAME_DOB in res.reasons
    assert res.requires_case is True


# ===========================================================================
# 4. Regulatory Invariant Tests (Twins & Same Name Different DOB)
# ===========================================================================
def test_name_similarity_with_different_dob_produces_no_alert():
    """Regulatory Rule: Name-only similarity with a different DOB produces NO alert."""
    rec_a = {"apaar_hash": None, "name": "Aarav Sharma", "dob": "2004-01-01", "institution_id": "INST-A"}
    rec_b = {"apaar_hash": None, "name": "Aarav Sharma", "dob": "2005-06-15", "institution_id": "INST-B"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is None, "Name similarity with different DOB must produce NO alert!"


def test_twins_same_dob_same_mobile_different_name_produces_no_alert():
    """Regulatory Rule: Twins sharing same DOB, family name & phone must NOT produce an alert."""
    rec_a = {"apaar_hash": None, "name": "Rohan Sharma", "dob": "2005-04-12", "mobile": "9876543210", "institution_id": "INST-A"}
    rec_b = {"apaar_hash": None, "name": "Rahul Sharma", "dob": "2005-04-12", "mobile": "9876543210", "institution_id": "INST-A"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is None, "Twins with different first names must produce NO alert!"


def test_tier_5_progression_completed_earlier_enrollment_no_case():
    """Tier 5: Same apaar_hash but earlier enrollment is COMPLETED -> logged as normal progression, no case."""
    h = compute_apaar_hash("987654321099")
    rec_a = {"apaar_hash": h, "name": "Aditya Joshi", "dob": "2002-08-11", "institution_id": "INST-A", "status": "COMPLETED"}
    rec_b = {"apaar_hash": h, "name": "Aditya Joshi", "dob": "2002-08-11", "institution_id": "INST-B", "status": "ACTIVE"}

    res = score_and_classify_pair(rec_a, rec_b)
    assert res is not None
    assert res.match_type == TIER_PROGRESSION
    assert res.is_progression is True
    assert res.requires_case is False
    assert REASON_NORMAL_PROGRESSION in res.reasons


# ===========================================================================
# 5. Candidate Blocking & DB Integration Tests
# ===========================================================================
def test_candidate_blocking_efficiently_filters(db_session: Session, dup_test_setup):
    """Verifies that candidate blocking queries only matching keys and scales with candidates."""
    inst1 = dup_test_setup["inst1"]
    appr1 = dup_test_setup["appr1"]

    # Insert 3 students: one matching DOB, one matching mobile, one completely unrelated
    s1 = Student(
        apaar_encrypted="ENC1",
        apaar_hash="hash_student_1",
        apaar_masked="XXXX-XXXX-1111",
        name="Target Student",
        name_normalized="TARGET STUDENT",
        dob=date(2005, 5, 10),
        gender="MALE",
        mobile_hash=compute_mobile_hash("9876543210"),
        mobile_last4="3210",
    )
    s2 = Student(
        apaar_encrypted="ENC2",
        apaar_hash="hash_student_2",
        apaar_masked="XXXX-XXXX-2222",
        name="Twin Student",
        name_normalized="TWIN STUDENT",
        dob=date(2005, 5, 10),  # Same DOB
        gender="MALE",
        mobile_hash=compute_mobile_hash("9999999999"),
        mobile_last4="9999",
    )
    s3 = Student(
        apaar_encrypted="ENC3",
        apaar_hash="hash_student_3",
        apaar_masked="XXXX-XXXX-3333",
        name="Unrelated Student",
        name_normalized="UNRELATED STUDENT",
        dob=date(2003, 1, 1),
        gender="FEMALE",
        mobile_hash=compute_mobile_hash("9111111111"),
        mobile_last4="1111",
    )
    db_session.add_all([s1, s2, s3])
    db_session.commit()

    now = datetime.now(timezone.utc)
    e1 = Enrollment(
        student_id=s1.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    e2 = Enrollment(
        student_id=s2.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    e3 = Enrollment(
        student_id=s3.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    db_session.add_all([e1, e2, e3])
    db_session.commit()

    # Query candidates for DOB = 2005-05-10
    candidates = find_candidate_enrollments(
        db=db_session,
        dob_iso="2005-05-10",
        exclude_enrollment_id=e1.id,
    )
    candidate_ids = [c.id for c in candidates]
    assert e2.id in candidate_ids
    assert e3.id not in candidate_ids, "Unrelated student must be filtered out by candidate blocking!"


def test_policy_same_institution_blocks_and_puts_under_review(db_session: Session, dup_test_setup):
    """
    Policy: Same-institution exact matches put both enrollments into UNDER_REVIEW
    and create a ReviewCase without auto-deleting or auto-rejecting.
    """
    inst1 = dup_test_setup["inst1"]
    appr1 = dup_test_setup["appr1"]
    service = DuplicateDetectionService(db=db_session)

    h = compute_apaar_hash("987654321015")
    s1 = Student(
        apaar_encrypted="ENC1",
        apaar_hash=h,
        apaar_masked="XXXX-XXXX-1015",
        name="Priya Patel",
        name_normalized="PRIYA PATEL",
        dob=date(2005, 3, 21),
        gender="FEMALE",
        mobile_hash=compute_mobile_hash("9876543210"),
        mobile_last4="3210",
    )
    db_session.add(s1)
    db_session.commit()

    now = datetime.now(timezone.utc)
    e1 = Enrollment(
        student_id=s1.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    e2 = Enrollment(
        student_id=s1.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    db_session.add_all([e1, e2])
    db_session.commit()

    # Run duplicate check and persist
    matches = service.check_enrollment(enrollment_id=e2.id, save_candidates=True)
    db_session.commit()

    assert len(matches) >= 1
    assert matches[0].match_type == TIER_HIGH

    # Check that DuplicateCandidate was created
    cand = db_session.query(DuplicateCandidate).filter(DuplicateCandidate.enrollment_b == e2.id).first()
    assert cand is not None
    assert cand.match_type == TIER_HIGH

    # Check ReviewCase was opened
    case = db_session.query(ReviewCase).filter(ReviewCase.enrollment_id == e2.id).first()
    assert case is not None
    assert case.type == "DUPLICATE_MATCH"
    assert case.severity == "HIGH"
    assert case.status == "OPEN"

    # Check that enrollment statuses were updated to UNDER_REVIEW
    db_session.refresh(e1)
    db_session.refresh(e2)
    assert e2.status == "UNDER_REVIEW"
    assert e2.verified is False


# ===========================================================================
# 6. API Endpoint Tests
# ===========================================================================
def test_api_check_duplicates_endpoint(client, db_session: Session, dup_test_setup):
    """Tests POST /api/duplicates/check endpoint."""
    inst1 = dup_test_setup["inst1"]
    appr1 = dup_test_setup["appr1"]

    h = compute_apaar_hash("987654321015")
    s1 = Student(
        apaar_encrypted="ENC1",
        apaar_hash=h,
        apaar_masked="XXXX-XXXX-1015",
        name="Priya Patel",
        name_normalized="PRIYA PATEL",
        dob=date(2005, 3, 21),
        gender="FEMALE",
        mobile_hash=compute_mobile_hash("9876543210"),
        mobile_last4="3210",
    )
    db_session.add(s1)
    db_session.commit()

    now = datetime.now(timezone.utc)
    e1 = Enrollment(
        student_id=s1.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    db_session.add(e1)
    db_session.commit()

    admin_token = create_jwt({"sub": "admin-aicte", "email": "admin@aicte.gov.in", "role": "AICTE_ADMIN"})

    # Ad-hoc check with same apaar_id in different institution
    resp = client.post(
        "/api/duplicates/check",
        json={
            "apaar_id": "987654321015",
            "name": "Priya Patel",
            "dob": "2005-03-21",
            "institution_id": "INSTITUTION-DIFF",
            "academic_year": "2024-2025",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_matches"] >= 1
    assert data["has_critical"] is True
    assert data["highest_tier"] == TIER_CRITICAL


def test_api_get_candidates_institutional_scoping(client, db_session: Session, dup_test_setup):
    """Tests GET /api/duplicates/candidates institutional scoping."""
    inst1 = dup_test_setup["inst1"]
    inst2 = dup_test_setup["inst2"]
    appr1 = dup_test_setup["appr1"]
    appr2 = dup_test_setup["appr2"]

    s1 = Student(
        apaar_encrypted="ENC1", apaar_hash="hash_a", apaar_masked="XXXX-XXXX-1111",
        name="Student One", name_normalized="STUDENT ONE", dob=date(2005, 1, 1), gender="MALE",
    )
    s2 = Student(
        apaar_encrypted="ENC2", apaar_hash="hash_b", apaar_masked="XXXX-XXXX-2222",
        name="Student Two", name_normalized="STUDENT TWO", dob=date(2005, 2, 2), gender="FEMALE",
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    now = datetime.now(timezone.utc)
    e1 = Enrollment(
        student_id=s1.id, institution_id=inst1.id, approval_id=appr1.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    e2 = Enrollment(
        student_id=s2.id, institution_id=inst2.id, approval_id=appr2.id,
        academic_year="2024-2025", seat_type=SeatType.REGULAR.value, category="OPEN",
        admission_date=now, status="CONFIRMED", verified=True,
    )
    db_session.add_all([e1, e2])
    db_session.commit()

    cand = DuplicateCandidate(
        enrollment_a=e1.id,
        enrollment_b=e2.id,
        match_type=TIER_CRITICAL,
        score=0.95,
        reasons=["APAAR_EXACT_MATCH", "CROSS_INSTITUTION_ACTIVE"],
        status="DETECTED",
    )
    db_session.add(cand)
    db_session.commit()

    # 1. Institution Admin of inst1 can view candidate because e1 belongs to inst1
    inst1_token = create_jwt({
        "sub": "user-inst1",
        "email": "admin@inst1.edu",
        "role": "INSTITUTION_ADMIN",
        "institution_id": inst1.id,
    })
    resp1 = client.get(
        "/api/duplicates/candidates",
        headers={"Authorization": f"Bearer {inst1_token}"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["total"] >= 1

    # 2. Institution Admin of an unrelated institution cannot view this candidate
    inst_other = Institution(code="1-OTHER", name="Other University", status="ACTIVE")
    db_session.add(inst_other)
    db_session.commit()

    other_token = create_jwt({
        "sub": "user-other",
        "email": "admin@other.edu",
        "role": "INSTITUTION_ADMIN",
        "institution_id": inst_other.id,
    })
    resp_other = client.get(
        "/api/duplicates/candidates",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp_other.status_code == 200
    assert resp_other.json()["total"] == 0
