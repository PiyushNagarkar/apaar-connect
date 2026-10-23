from datetime import date, datetime, timezone
import pytest

from backend.models.institution import Institution
from backend.models.user import User
from backend.models.approval import ProgramApproval, ApprovalStatus
from backend.models.seat import SeatAllocation, SeatType
from backend.models.student import Student
from backend.models.enrollment import Enrollment
from backend.schemas.errors import AppException
from backend.security.crypto import create_jwt
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_AUDITOR,
)
from backend.services.approval_service import (
    create_approval,
    update_draft_approval,
    freeze_approval,
    supersede_approval,
    get_approval_history,
    import_approvals_csv,
    calculate_seat_matrix,
    HANDBOOK_NOTE,
)


@pytest.fixture
def approval_fixtures(db_session):
    """Seed base institution and users for approval testing."""
    inst_a = Institution(code="1-APP-INST-A", name="IIT Delhi", status="ACTIVE")
    inst_b = Institution(code="1-APP-INST-B", name="NIT Trichy", status="ACTIVE")
    db_session.add_all([inst_a, inst_b])
    db_session.commit()

    token_aicte_admin = create_jwt({
        "sub": "user-admin-01",
        "email": "admin@aicte.gov.in",
        "role": ROLE_AICTE_ADMIN,
    })
    token_inst_op_a = create_jwt({
        "sub": "user-op-a",
        "email": "operator.a@iitd.ac.in",
        "role": ROLE_INSTITUTION_OPERATOR,
        "institution_id": str(inst_a.id),
    })

    return {
        "inst_a": inst_a,
        "inst_b": inst_b,
        "token_aicte_admin": token_aicte_admin,
        "token_inst_op_a": token_inst_op_a,
    }


def test_frozen_row_cannot_be_edited(approval_fixtures, db_session):
    """
    Test rule: FREEZE makes the approval and its allocations immutable.
    Attempts to edit a frozen approval must be rejected with HTTP 409.
    """
    inst = approval_fixtures["inst_a"]

    # 1. Create DRAFT approval
    approval = create_approval(
        db=db_session,
        institution_id=str(inst.id),
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        academic_year="2024-2025",
        approval_ref="EOA-TEST-001",
        allocations={"REGULAR": 120, "NRI": 15},
    )
    assert approval.status == ApprovalStatus.DRAFT

    # 2. Freeze the approval
    frozen = freeze_approval(
        db=db_session,
        approval_id=str(approval.id),
        actor_email="admin@aicte.gov.in",
        actor_id="user-admin-01",
    )
    assert frozen.status == ApprovalStatus.FROZEN
    assert frozen.frozen_at is not None

    # 3. Attempt update on frozen row via service
    with pytest.raises(AppException) as exc_info:
        update_draft_approval(
            db=db_session,
            approval_id=str(approval.id),
            updates={"branch": "ARTIFICIAL_INTELLIGENCE"},
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "APPROVAL_FROZEN_IMMUTABLE"


def test_version_2_doesnt_alter_version_1(approval_fixtures, db_session):
    """
    Test rule: A correction creates version N+1 with supersedes_id and a mandatory reason;
    old version stays readable and completely unaltered.
    """
    inst = approval_fixtures["inst_a"]

    # 1. Create and Freeze Version 1
    v1 = create_approval(
        db=db_session,
        institution_id=str(inst.id),
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="COMPUTER_SCIENCE_AND_ENGINEERING",
        academic_year="2024-2025",
        approval_ref="EOA-NORTH-2024-IITD",
        allocations={"REGULAR": 120, "NRI": 15, "SUPERNUMERARY_FN_OCI_PIO": 10},
    )
    freeze_approval(db=db_session, approval_id=str(v1.id), actor_email="admin@aicte.gov.in", actor_id="admin-01")
    v1_id = str(v1.id)

    # 2. Supersede to create Version 2
    change_reason = "Sanctioned EoA Amendment: increased regular intake to 150 seats."
    v2 = supersede_approval(
        db=db_session,
        approval_id=v1_id,
        change_reason=change_reason,
        allocations={"REGULAR": 150, "NRI": 20, "SUPERNUMERARY_FN_OCI_PIO": 10},
        actor_email="admin@aicte.gov.in",
        actor_id="admin-01",
    )

    assert v2.version == 2
    assert str(v2.supersedes_id) == v1_id

    # 3. Verify Version 1 remains completely unaltered
    db_session.expire_all()
    v1_fetched = db_session.query(ProgramApproval).filter(ProgramApproval.id == v1_id).first()
    assert v1_fetched.version == 1
    assert v1_fetched.status == ApprovalStatus.FROZEN
    v1_allocs = {a.seat_type.value: a.approved_count for a in v1_fetched.seat_allocations}
    assert v1_allocs["REGULAR"] == 120
    assert v1_allocs["NRI"] == 15

    # 4. Verify Version 2 has new updated allocations
    v2_allocs = {a.seat_type.value: a.approved_count for a in v2.seat_allocations}
    assert v2_allocs["REGULAR"] == 150
    assert v2_allocs["NRI"] == 20


def test_institution_user_cannot_post_approvals(client, approval_fixtures):
    """
    Test rule: Institutions get read-only access to their own approvals.
    Institution users cannot call POST write endpoints (returns 403 Forbidden).
    """
    token_op = approval_fixtures["token_inst_op_a"]
    inst_id = str(approval_fixtures["inst_a"].id)

    # Institution user attempts to create approval
    res1 = client.post(
        "/api/admin/approvals",
        headers={"Authorization": f"Bearer {token_op}"},
        json={
            "institution_id": inst_id,
            "programme": "ENG",
            "branch": "MECH",
            "academic_year": "2024-2025",
            "approval_ref": "ILLEGAL-OP-REF",
        },
    )
    assert res1.status_code == 403
    assert res1.json()["code"] == "FORBIDDEN"

    # Institution user attempts to import CSV
    res2 = client.post(
        "/api/admin/approvals/import",
        headers={"Authorization": f"Bearer {token_op}"},
        json={"csv_content": "col1,col2", "commit": False},
    )
    assert res2.status_code == 403


def test_utilisation_formula(approval_fixtures, db_session):
    """
    Test rule: seat-matrix endpoint returns per seat_type:
    approved, confirmed+active occupied, provisional (shown separately), available, utilisation %.
    Formula: utilisation % = (occupied / approved) * 100.
    """
    inst = approval_fixtures["inst_a"]

    # 1. Create and freeze approval with 100 REGULAR seats
    appr = create_approval(
        db=db_session,
        institution_id=str(inst.id),
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="ELECTRICAL_ENGINEERING",
        academic_year="2024-2025",
        approval_ref="EOA-EE-100",
        allocations={"REGULAR": 100},
    )
    freeze_approval(db=db_session, approval_id=str(appr.id), actor_email="admin@aicte.gov.in", actor_id="admin-01")

    # 2. Add 40 Confirmed enrollments and 20 Provisional enrollments
    now = datetime.now(timezone.utc)
    for i in range(40):
        std = Student(
            apaar_encrypted="enc", apaar_hash=f"hash_conf_{i}", apaar_masked=f"M_{i}",
            name=f"Student {i}", name_normalized=f"STUDENT {i}", dob=date(2005, 1, 1), gender="MALE"
        )
        db_session.add(std)
        db_session.flush()
        enr = Enrollment(
            student_id=std.id, institution_id=inst.id, approval_id=appr.id,
            academic_year="2024-2025", seat_type="REGULAR", category="OPEN",
            admission_date=now, status="CONFIRMED", verified=True
        )
        db_session.add(enr)

    for j in range(20):
        std = Student(
            apaar_encrypted="enc", apaar_hash=f"hash_prov_{j}", apaar_masked=f"M_P_{j}",
            name=f"Student P {j}", name_normalized=f"STUDENT P {j}", dob=date(2005, 1, 1), gender="FEMALE"
        )
        db_session.add(std)
        db_session.flush()
        enr = Enrollment(
            student_id=std.id, institution_id=inst.id, approval_id=appr.id,
            academic_year="2024-2025", seat_type="REGULAR", category="OPEN",
            admission_date=now, status="PROVISIONAL", verified=False
        )
        db_session.add(enr)

    db_session.commit()

    # 3. Calculate seat matrix
    matrix_res = calculate_seat_matrix(
        db=db_session,
        institution_id=str(inst.id),
        academic_year="2024-2025",
        approval_id=str(appr.id),
    )

    regular_entry = next(item for item in matrix_res["seat_matrix"] if item["seat_type"] == "REGULAR")
    assert regular_entry["approved"] == 100
    assert regular_entry["confirmed_active"] == 40
    assert regular_entry["provisional"] == 20
    assert regular_entry["occupied_total"] == 60
    assert regular_entry["available"] == 40
    # Exact utilisation percentage: (60 / 100) * 100 = 60.0%
    assert regular_entry["utilisation_pct"] == 60.0
    assert regular_entry["warning"] is None
    assert matrix_res["handbook_note"] == HANDBOOK_NOTE


def test_zero_approved_handling(approval_fixtures, db_session):
    """
    Test rule: Handle approved=0 explicitly.
    Any admission in that category is flagged 'no approval for this category',
    and utilisation_pct is 0.0 without ZeroDivisionError.
    """
    inst = approval_fixtures["inst_a"]

    # Create approval where NRI = 0 approved
    appr = create_approval(
        db=db_session,
        institution_id=str(inst.id),
        programme="ENGINEERING_AND_TECHNOLOGY",
        branch="CIVIL_ENGINEERING",
        academic_year="2024-2025",
        approval_ref="EOA-CIVIL-ZERO-NRI",
        allocations={"REGULAR": 60, "NRI": 0},
    )
    freeze_approval(db=db_session, approval_id=str(appr.id), actor_email="admin@aicte.gov.in", actor_id="admin-01")

    # Add an admission under NRI (0 approved seats)
    now = datetime.now(timezone.utc)
    std = Student(
        apaar_encrypted="enc", apaar_hash="hash_unapproved_nri", apaar_masked="M_NRI",
        name="NRI Student", name_normalized="NRI STUDENT", dob=date(2005, 1, 1), gender="MALE"
    )
    db_session.add(std)
    db_session.flush()
    enr = Enrollment(
        student_id=std.id, institution_id=inst.id, approval_id=appr.id,
        academic_year="2024-2025", seat_type="NRI", category="OPEN",
        admission_date=now, status="PROVISIONAL", verified=False
    )
    db_session.add(enr)
    db_session.commit()

    matrix_res = calculate_seat_matrix(
        db=db_session,
        institution_id=str(inst.id),
        approval_id=str(appr.id),
    )

    nri_entry = next(item for item in matrix_res["seat_matrix"] if item["seat_type"] == "NRI")
    assert nri_entry["approved"] == 0
    assert nri_entry["occupied_total"] == 1
    assert nri_entry["utilisation_pct"] == 0.0
    assert nri_entry["warning"] == "no approval for this category"


def test_acceptance_check_csv_import_freeze_v2_history_diff(client, approval_fixtures, db_session):
    """
    Acceptance check:
    1. Import a sample CSV
    2. Freeze it
    3. Create v2
    4. Show the history diff.
    """
    token_admin = approval_fixtures["token_aicte_admin"]
    inst_code = approval_fixtures["inst_a"].code

    csv_data = f"""institution_code,programme,branch,campus,shift,academic_year,approval_ref,regular_seats,nri_seats,fn_seats,gulf_seats,other_seats,rule_version
{inst_code},ENGINEERING_AND_TECHNOLOGY,ARTIFICIAL_INTELLIGENCE_AND_DATA_SCIENCE,MAIN,FIRST,2024-2025,EOA-AICTE-AIDS-2024,60,5,0,0,0,AICTE_HANDBOOK_2024_25_V1
"""

    # 1. Preview CSV import (commit=False)
    preview_res = client.post(
        "/api/admin/approvals/import",
        headers={"Authorization": f"Bearer {token_admin}"},
        json={"csv_content": csv_data, "commit": False},
    )
    assert preview_res.status_code == 200
    assert preview_res.json()["valid_rows"] == 1
    assert preview_res.json()["invalid_rows"] == 0

    # Commit CSV import
    import_res = client.post(
        "/api/admin/approvals/import",
        headers={"Authorization": f"Bearer {token_admin}"},
        json={"csv_content": csv_data, "commit": True},
    )
    assert import_res.status_code == 200
    created_ids = import_res.json()["created_ids"]
    assert len(created_ids) == 1
    v1_id = created_ids[0]

    # 2. Freeze approval v1
    freeze_res = client.post(
        f"/api/admin/approvals/{v1_id}/freeze",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert freeze_res.status_code == 200
    assert freeze_res.json()["status"] == "FROZEN"

    # 3. Create v2 with supersedes_id and change reason
    supersede_res = client.post(
        f"/api/admin/approvals/{v1_id}/supersede",
        headers={"Authorization": f"Bearer {token_admin}"},
        json={
            "change_reason": "Increased regular seats from 60 to 90 per Regional Committee approval",
            "allocations": {"REGULAR": 90, "NRI": 10},
        },
    )
    assert supersede_res.status_code == 200
    v2_data = supersede_res.json()
    assert v2_data["version"] == 2
    assert v2_data["supersedes_id"] == v1_id
    assert v2_data["allocations"]["REGULAR"] == 90

    # 4. Show the history diff
    history_res = client.get(
        f"/api/admin/approvals/{v1_id}/history",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert history_res.status_code == 200
    history = history_res.json()
    assert history["total_versions"] == 2
    v1_hist = history["history"][0]
    v2_hist = history["history"][1]

    assert v1_hist["version"] == 1
    assert v1_hist["status"] == "FROZEN"
    assert v1_hist["seat_allocations"]["REGULAR"] == 60

    assert v2_hist["version"] == 2
    assert v2_hist["supersedes_id"] == v1_id
    assert v2_hist["seat_allocations"]["REGULAR"] == 90
    assert "Increased regular seats" in v2_hist["change_reason"]

    # Verify allocation diff in history
    diff = v2_hist["diff_from_previous"]
    assert "seat_allocations" in diff
    assert diff["seat_allocations"]["REGULAR"]["old"] == 60
    assert diff["seat_allocations"]["REGULAR"]["new"] == 90
    assert diff["seat_allocations"]["REGULAR"]["delta"] == 30
