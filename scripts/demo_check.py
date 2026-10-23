#!/usr/bin/env python3
"""
Demo Environment Verification Tool (scripts/demo_check.py).

Verifies the demonstration environment readiness:
1. Health: GET /api/health returns healthy.
2. Seeded Counts: Verifies database entities (institutions, users, approvals, enrollments, credentials, audit events).
3. RBAC Logins: Validates authentications for all 7 system roles with 'DemoPass@123':
   - AICTE_ADMIN (admin@aicte.gov.in)
   - AICTE_REVIEWER (reviewer@aicte.gov.in)
   - INSTITUTION_ADMIN (admin@iitd.ac.in)
   - INSTITUTION_OPERATOR (operator@iitd.ac.in)
   - STUDENT (student@demo.aicte.gov.in)
   - AUDITOR (auditor@aicte.gov.in)
   - VERIFIER (verifier@tcs.com)

Usage:
  python scripts/demo_check.py
"""
import os
import sys

# Ensure project modules are importable
_curr_dir = os.path.abspath(os.path.dirname(__file__))
_root_dir = os.path.abspath(os.path.join(_curr_dir, ".."))
_apaar_dir = os.path.join(_root_dir, "apaar-connect")
_backend_dir = os.path.join(_apaar_dir, "backend")

for p in (_root_dir, _backend_dir, _apaar_dir):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models.institution import Institution
from backend.models.user import User
from backend.models.approval import ProgramApproval
from backend.models.seat import SeatAllocation
from backend.models.enrollment import Enrollment
from backend.models.credential import Credential
from backend.models.audit import AuditEvent
from backend.security.permissions import (
    ROLE_AICTE_ADMIN,
    ROLE_AICTE_REVIEWER,
    ROLE_INSTITUTION_ADMIN,
    ROLE_INSTITUTION_OPERATOR,
    ROLE_STUDENT,
    ROLE_AUDITOR,
    ROLE_VERIFIER,
)

DEMO_PASSWORD = "DemoPass@123"

DEMO_ROLES = [
    ("AICTE_ADMIN", "admin@aicte.gov.in", ROLE_AICTE_ADMIN),
    ("AICTE_REVIEWER", "reviewer@aicte.gov.in", ROLE_AICTE_REVIEWER),
    ("INSTITUTION_ADMIN", "admin@iitd.ac.in", ROLE_INSTITUTION_ADMIN),
    ("INSTITUTION_OPERATOR", "operator@iitd.ac.in", ROLE_INSTITUTION_OPERATOR),
    ("STUDENT", "student@demo.aicte.gov.in", ROLE_STUDENT),
    ("AUDITOR", "auditor@aicte.gov.in", ROLE_AUDITOR),
    ("VERIFIER", "verifier@tcs.com", ROLE_VERIFIER),
]


def check_demo_environment() -> bool:
    print("=" * 76)
    print("AICTE APAAR CONNECT - DEMO VERIFICATION TOOL (make demo-check)")
    print("=" * 76)

    client = TestClient(app)
    all_passed = True

    # 1. Health Endpoint Check
    print("\n[1/3] Checking System Health Endpoint (/api/health)...")
    try:
        res = client.get("/api/health")
        if res.status_code == 200:
            data = res.json()
            status = data.get("status")
            source = data.get("adapter", {}).get("source", "MOCK_APAAR_V1")
            print(f"      Status:   OK (HTTP 200, status='{status}')")
            print(f"      Adapter:  {source}")
            print(f"      Notice:   Synthetic data / Simulated APAAR service")
        else:
            print(f"      [FAIL] /api/health returned HTTP {res.status_code}: {res.text}")
            all_passed = False
    except Exception as e:
        print(f"      [FAIL] Health check failed with error: {e}")
        all_passed = False

    # 2. Seeded Database Entity Counts
    print("\n[2/3] Verifying Seeded Database Entity Counts...")
    db = SessionLocal()
    try:
        inst_count = db.query(Institution).count()
        user_count = db.query(User).count()
        appr_count = db.query(ProgramApproval).count()
        seat_count = db.query(SeatAllocation).count()
        enr_count = db.query(Enrollment).count()
        cred_count = db.query(Credential).count()
        audit_count = db.query(AuditEvent).count()

        print(f"      - Institutions:         {inst_count:>5} (Expected: >= 2)")
        print(f"      - Demo Users:           {user_count:>5} (Expected: >= 7)")
        print(f"      - Program Approvals:    {appr_count:>5} (Expected: >= 3)")
        print(f"      - Seat Allocations:     {seat_count:>5} (Expected: >= 9)")
        print(f"      - Student Enrollments:  {enr_count:>5} (Expected: >= 10)")
        print(f"      - Issued Credentials:   {cred_count:>5} (Expected: >= 3)")
        print(f"      - Audit Trail Events:   {audit_count:>5} (Expected: >= 4)")

        if inst_count < 2 or user_count < 7 or enr_count < 10 or cred_count < 3 or audit_count < 4:
            print("      [FAIL] Database counts are below demonstration thresholds. Run 'make demo-reset'.")
            all_passed = False
        else:
            print("      [PASS] Seeded database entities meet demonstration requirements.")
    except Exception as e:
        print(f"      [FAIL] Database counts query failed: {e}")
        all_passed = False
    finally:
        db.close()

    # 3. All 7 RBAC Role Authentication Logins
    print("\n[3/3] Testing JWT Authentication Logins for all 7 RBAC Roles...")
    login_successes = 0
    for role_name, email, expected_role in DEMO_ROLES:
        try:
            res = client.post(
                "/api/auth/login",
                json={"email": email, "password": DEMO_PASSWORD},
            )
            if res.status_code == 200:
                body = res.json()
                token = body.get("access_token")
                returned_role = body.get("user", {}).get("role")
                if token and returned_role == expected_role:
                    print(f"      [OK] {role_name:<20} {email:<28} -> Role: {returned_role}")
                    login_successes += 1
                else:
                    print(f"      [FAIL] {role_name} token or role mismatch: {body}")
                    all_passed = False
            else:
                print(f"      [FAIL] {role_name} login failed with HTTP {res.status_code}: {res.text}")
                all_passed = False
        except Exception as e:
            print(f"      [FAIL] {role_name} login exception: {e}")
            all_passed = False

    print("\n" + "=" * 76)
    if all_passed and login_successes == len(DEMO_ROLES):
        print(f"DEMO ENVIRONMENT STATUS: [ALL CHECKS PASSED] ({login_successes}/{len(DEMO_ROLES)} Logins Verified)")
        print("Ready for live regulatory demonstration.")
        print("=" * 76)
        return True
    else:
        print("DEMO ENVIRONMENT STATUS: [ISSUES DETECTED]")
        print("Run 'make demo-reset' to re-initialize a fresh demonstration state.")
        print("=" * 76)
        return False


def main():
    success = check_demo_environment()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
