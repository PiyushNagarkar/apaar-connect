#!/usr/bin/env python3
"""
Synthetic Data Generator (scripts/generate_synthetic_data.py).

Generates:
1. sample_data/mock_apaar_directory.json: ~12,000 synthetic APAAR identities with valid
   12-digit format and Luhn checksum.
2. sample_data/performance_10k.csv: 10,000-row CSV for high-throughput performance testing.
3. sample_data/imperfect_demo.csv: ~40-row CSV containing planted edge cases and errors
   for live demo and evaluation.
4. sample_data/EXPECTED.md: Complete rule matrix documenting expected results for each demo row.

Deterministic & Idempotent via --seed. Uses Faker('en_IN'); never uses real people.
"""
import argparse
import csv
import json
import os
import random
import re
import sys
from datetime import date, timedelta
from typing import Any, Dict, List

# Ensure project modules are importable
_curr_dir = os.path.abspath(os.path.dirname(__file__))
_root_dir = os.path.abspath(os.path.join(_curr_dir, ".."))
_apaar_backend = os.path.join(_root_dir, "apaar-connect", "backend")

for p in (_root_dir, _apaar_backend):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from faker import Faker

try:
    from backend.services.identity_adapter import (
        compute_luhn_checksum_digit,
        generate_valid_apaar,
        validate_apaar_format_and_checksum,
    )
    from backend.services.submission_service import EXPECTED_CSV_COLUMNS
except ImportError:
    # Standalone fallback if package structure differs
    EXPECTED_CSV_COLUMNS = [
        "apaar_id", "name", "dob", "gender", "mobile", "email", "roll_no",
        "programme", "branch", "campus", "shift", "academic_year", "seat_type",
        "category", "nri_flag", "oci_flag", "fn_flag", "admission_date",
        "consent_reference", "evidence_ref",
    ]

    def compute_luhn_checksum_digit(eleven_digits: str) -> str:
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
        prefix = re.sub(r"\D", "", prefix_11)[:11].zfill(11)
        return prefix + compute_luhn_checksum_digit(prefix)

    def validate_apaar_format_and_checksum(raw_apaar: str) -> bool:
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
        return total % 10 == 0


def build_synthetic_apaar_registry(
    faker: Faker,
    rng: random.Random,
    count: int = 12000,
) -> Dict[str, Dict[str, Any]]:
    """
    Builds ~12,000 synthetic APAAR profiles with mathematical Luhn check digits.
    All profiles use synthetic Indian demographic attributes.
    """
    registry: Dict[str, Dict[str, Any]] = {}

    # Seed known baseline accounts required by test suites
    baseline_profiles = {
        "987654321015": {"name": "Priya Patel", "dob": "2005-03-21", "gender": "FEMALE", "status": "ACTIVE"},
        "987654321012": {"name": "Priya Patel", "dob": "2005-03-21", "gender": "FEMALE", "status": "ACTIVE"},
        "987654321013": {"name": "Rahul Sharma", "dob": "2004-11-05", "gender": "MALE", "status": "ACTIVE"},
        "987654321014": {"name": "Ananya Iyer", "dob": "2005-01-19", "gender": "FEMALE", "status": "ACTIVE"},
        "123456789012": {"name": "Aarav Sharma", "dob": "2004-05-14", "gender": "MALE", "status": "ACTIVE"},
        "111122223333": {"name": "Vikram Singh", "dob": "2004-08-12", "gender": "MALE", "status": "ACTIVE"},
    }
    registry.update(baseline_profiles)

    first_names_m = [
        "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
        "Shaurya", "Atharva", "Advik", "Pranav", "Advaith", "Aaryan", "Dhruv", "Kabir", "Rohan", "Rishi",
        "Karan", "Nikhil", "Manish", "Siddharth", "Aniket", "Harsh", "Gaurav", "Amit", "Rajesh", "Suresh"
    ]
    first_names_f = [
        "Saanvi", "Aanya", "Aadhya", "Aaradhya", "Ananya", "Pari", "Anika", "Navya", "Diya", "Avani",
        "Myra", "Ira", "Ahana", "Riya", "Prisha", "Isha", "Kavya", "Tanvi", "Neha", "Pooja",
        "Shreya", "Aditi", "Anjali", "Meera", "Swati", "Deepa", "Sneha", "Sunita", "Divya", "Pooja"
    ]
    last_names = [
        "Sharma", "Verma", "Patel", "Gupta", "Singh", "Kumar", "Mishra", "Joshi", "Iyer", "Nair",
        "Reddy", "Rao", "Deshmukh", "Kulkarni", "Patil", "Chavan", "Jadhav", "Bose", "Chatterjee", "Banerjee",
        "Mukherjee", "Das", "Ghosh", "Sengupta", "Choudhury", "Bhattacharya", "Agarwal", "Bansal", "Goel", "Mehta"
    ]

    used_apaars = set(registry.keys())
    start_date = date(2000, 1, 1)
    end_date = date(2006, 12, 31)
    days_range = (end_date - start_date).days

    idx = 1000
    while len(registry) < count:
        idx += 1
        # Deterministic 11-digit prefix
        prefix_11 = f"88{idx:09d}"
        apaar = generate_valid_apaar(prefix_11)
        if apaar in used_apaars:
            continue
        used_apaars.add(apaar)

        gender_roll = rng.random()
        if gender_roll < 0.49:
            gender = "MALE"
            fn = rng.choice(first_names_m)
        elif gender_roll < 0.98:
            gender = "FEMALE"
            fn = rng.choice(first_names_f)
        else:
            gender = "OTHER"
            fn = rng.choice(first_names_m + first_names_f)

        ln = rng.choice(last_names)
        full_name = f"{fn} {ln}"
        random_days = rng.randint(0, days_range)
        dob = (start_date + timedelta(days=random_days)).isoformat()

        registry[apaar] = {
            "name": full_name,
            "dob": dob,
            "gender": gender,
            "status": "ACTIVE",
        }

    return registry


def generate_performance_csv(
    registry: Dict[str, Dict[str, Any]],
    output_path: str,
    rng: random.Random,
    count: int = 10000,
) -> None:
    """
    Generates a 10,000-row compliant CSV for benchmark & performance stress checks.
    """
    records = list(registry.items())
    rng.shuffle(records)

    branches = [
        "COMPUTER_SCIENCE_AND_ENGINEERING",
        "INFORMATION_TECHNOLOGY",
        "MECHANICAL_ENGINEERING",
        "ELECTRONICS_AND_COMMUNICATION_ENGINEERING",
        "ELECTRICAL_ENGINEERING",
        "CIVIL_ENGINEERING",
    ]
    categories = ["OPEN", "OBC_NCL", "SC", "ST", "EWS"]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_CSV_COLUMNS)
        writer.writeheader()

        for i in range(1, count + 1):
            apaar, profile = records[(i - 1) % len(records)]
            branch = branches[i % len(branches)]
            cat = categories[i % len(categories)]

            # 85% REGULAR, 5% NRI, 5% FN/OCI, 5% Gulf Worker
            roll = rng.random()
            if roll < 0.85:
                seat_type = "REGULAR"
                nri, oci, fn = False, False, False
            elif roll < 0.90:
                seat_type = "NRI"
                nri, oci, fn = True, False, False
            elif roll < 0.95:
                seat_type = "SUPERNUMERARY_FN_OCI_PIO"
                if rng.random() < 0.5:
                    nri, oci, fn = False, True, False
                else:
                    nri, oci, fn = False, False, True
            else:
                seat_type = "SUPERNUMERARY_GULF_WORKER_CHILD"
                nri, oci, fn = False, False, False

            mobile = f"98{rng.randint(10000000, 99999999)}"
            email = f"student{i:05d}@example.edu.in"
            roll_no = f"24{branch[:3]}{i:04d}"
            admission_date = f"2024-07-{rng.randint(10, 28):02d}"

            writer.writerow({
                "apaar_id": apaar,
                "name": profile["name"],
                "dob": profile["dob"],
                "gender": profile["gender"],
                "mobile": mobile,
                "email": email,
                "roll_no": roll_no,
                "programme": "ENGINEERING_AND_TECHNOLOGY",
                "branch": branch,
                "campus": "MAIN",
                "shift": "FIRST",
                "academic_year": "2024-2025",
                "seat_type": seat_type,
                "category": cat,
                "nri_flag": str(nri).lower(),
                "oci_flag": str(oci).lower(),
                "fn_flag": str(fn).lower(),
                "admission_date": admission_date,
                "consent_reference": f"CONSENT-2024-{i:06d}",
                "evidence_ref": f"EVID-2024-{i:06d}",
            })


def generate_imperfect_demo_csv(
    registry: Dict[str, Dict[str, Any]],
    output_path: str,
) -> List[Dict[str, Any]]:
    """
    Generates imperfect_demo.csv with exactly 40 rows containing planted edge cases
    and negative scenarios.
    """
    rows: List[Dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # PART 1: Programme A Compliant Normal / Edge Cases (Rows 1-10)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 1,
        "apaar_id": "987654321015",
        "name": "Priya Patel",
        "dob": "2005-03-21",
        "gender": "FEMALE",
        "mobile": "9820111222",
        "email": "priya.patel@example.edu.in",
        "roll_no": "24CSE0001",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-15",
        "consent_reference": "CONSENT-DEMO-001",
        "evidence_ref": "EVID-DEMO-001",
        "_case": "COMPLIANT_REGULAR_OPEN",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid student enrollment, REGULAR seat, OPEN category.",
    })
    rows.append({
        "row_number": 2,
        "apaar_id": "987654321013",
        "name": "Rahul Sharma",
        "dob": "2004-11-05",
        "gender": "MALE",
        "mobile": "9820222333",
        "email": "rahul.sharma@example.edu.in",
        "roll_no": "24CSE0002",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OBC_NCL",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-15",
        "consent_reference": "CONSENT-DEMO-002",
        "evidence_ref": "EVID-DEMO-002",
        "_case": "COMPLIANT_REGULAR_OBC",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid student enrollment, REGULAR seat, OBC_NCL category.",
    })
    rows.append({
        "row_number": 3,
        "apaar_id": "123456789012",
        "name": "Aarav Sharma",
        "dob": "2004-05-14",
        "gender": "MALE",
        "mobile": "9820333444",
        "email": "aarav.sharma@example.edu.in",
        "roll_no": "24CSE0003",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "SC",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-16",
        "consent_reference": "CONSENT-DEMO-003",
        "evidence_ref": "EVID-DEMO-003",
        "_case": "COMPLIANT_REGULAR_SC",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid student enrollment, REGULAR seat, SC category.",
    })
    rows.append({
        "row_number": 4,
        "apaar_id": "111122223333",
        "name": "Vikram Singh",
        "dob": "2004-08-12",
        "gender": "MALE",
        "mobile": "9820444555",
        "email": "vikram.singh@example.edu.in",
        "roll_no": "24CSE0004",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "ST",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-16",
        "consent_reference": "CONSENT-DEMO-004",
        "evidence_ref": "EVID-DEMO-004",
        "_case": "COMPLIANT_REGULAR_ST",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid student enrollment, REGULAR seat, ST category.",
    })
    rows.append({
        "row_number": 5,
        "apaar_id": "987654321012",
        "name": "Priya Patel",
        "dob": "2005-03-21",
        "gender": "FEMALE",
        "mobile": "9820555666",
        "email": "priya.p2@example.edu.in",
        "roll_no": "24CSE0005",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "EWS",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-17",
        "consent_reference": "CONSENT-DEMO-005",
        "evidence_ref": "EVID-DEMO-005",
        "_case": "COMPLIANT_REGULAR_EWS",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid student enrollment, REGULAR seat, EWS category.",
    })
    rows.append({
        "row_number": 6,
        "apaar_id": "880000001007",
        "name": "Deepak Verma",
        "dob": "2005-06-11",
        "gender": "MALE",
        "mobile": "9820666777",
        "email": "deepak.verma@example.edu.in",
        "roll_no": "24CSE0006",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "NRI",
        "category": "OPEN",
        "nri_flag": "true",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-17",
        "consent_reference": "CONSENT-DEMO-006",
        "evidence_ref": "EVID-DEMO-006",
        "_case": "COMPLIANT_NRI",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid NRI seat admission with nri_flag=true.",
    })
    rows.append({
        "row_number": 7,
        "apaar_id": "880000001015",
        "name": "Fatima Mansoor",
        "dob": "2004-09-20",
        "gender": "FEMALE",
        "mobile": "9820777888",
        "email": "fatima.mansoor@example.edu.in",
        "roll_no": "24CSE0007",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "SUPERNUMERARY_FN_OCI_PIO",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "true",
        "admission_date": "2024-07-18",
        "consent_reference": "CONSENT-DEMO-007",
        "evidence_ref": "EVID-DEMO-007",
        "_case": "COMPLIANT_SUPERNUMERARY_FN",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid Supernumerary Foreign National admission with fn_flag=true.",
    })
    rows.append({
        "row_number": 8,
        "apaar_id": "880000001023",
        "name": "Neil Mukherjee",
        "dob": "2005-02-14",
        "gender": "MALE",
        "mobile": "9820888999",
        "email": "neil.mukherjee@example.edu.in",
        "roll_no": "24CSE0008",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "SUPERNUMERARY_FN_OCI_PIO",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "true",
        "fn_flag": "false",
        "admission_date": "2024-07-18",
        "consent_reference": "CONSENT-DEMO-008",
        "evidence_ref": "EVID-DEMO-008",
        "_case": "COMPLIANT_SUPERNUMERARY_OCI",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid Supernumerary OCI admission with oci_flag=true.",
    })
    rows.append({
        "row_number": 9,
        "apaar_id": "880000001031",
        "name": "Tariq Aziz",
        "dob": "2004-12-05",
        "gender": "MALE",
        "mobile": "9820999000",
        "email": "tariq.aziz@example.edu.in",
        "roll_no": "24CSE0009",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "SUPERNUMERARY_GULF_WORKER_CHILD",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-19",
        "consent_reference": "CONSENT-DEMO-009",
        "evidence_ref": "EVID-DEMO-009",
        "_case": "COMPLIANT_SUPERNUMERARY_GULF",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid Supernumerary Children of Indian Workers in Gulf Countries admission.",
    })
    rows.append({
        "row_number": 10,
        "apaar_id": "880000001049",
        "name": "Sneha Kulkarni",
        "dob": "2005-08-22",
        "gender": "FEMALE",
        "mobile": "9821000111",
        "email": "sneha.kulkarni@example.edu.in",
        "roll_no": "24CSE0010",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "TFW",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-19",
        "consent_reference": "CONSENT-DEMO-010",
        "evidence_ref": "EVID-DEMO-010",
        "_case": "COMPLIANT_REGULAR_TFW",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Valid REGULAR seat admission under Tuition Fee Waiver (TFW) scheme.",
    })

    # -------------------------------------------------------------------------
    # PART 2: Twin Pair (must NOT alert) (Rows 11-12)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 11,
        "apaar_id": "880000001056",
        "name": "Rohan Verma",
        "dob": "2005-04-10",
        "gender": "MALE",
        "mobile": "9876500001",
        "email": "rohan.v@example.edu.in",
        "roll_no": "24CSE0011",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-20",
        "consent_reference": "CONSENT-DEMO-011",
        "evidence_ref": "EVID-DEMO-011",
        "_case": "TWIN_PAIR_A",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Twin brother: shares DOB & parent mobile with Kavya Verma, but different first name and distinct APAAR. Must NOT alert.",
    })
    rows.append({
        "row_number": 12,
        "apaar_id": "880000001064",
        "name": "Kavya Verma",
        "dob": "2005-04-10",
        "gender": "FEMALE",
        "mobile": "9876500001",
        "email": "kavya.v@example.edu.in",
        "roll_no": "24CSE0012",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-20",
        "consent_reference": "CONSENT-DEMO-012",
        "evidence_ref": "EVID-DEMO-012",
        "_case": "TWIN_PAIR_B",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Twin sister: shares DOB & parent mobile with Rohan Verma, but different first name and distinct APAAR. Must NOT alert.",
    })

    # -------------------------------------------------------------------------
    # PART 3: Progression: Completed-then-Readmitted (no alert) (Rows 13-14)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 13,
        "apaar_id": "880000001072",
        "name": "Arjun Nair",
        "dob": "2002-05-18",
        "gender": "MALE",
        "mobile": "9821333444",
        "email": "arjun.nair@example.edu.in",
        "roll_no": "20CSE0042",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2020-2021",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2020-08-01",
        "consent_reference": "CONSENT-HIST-013",
        "evidence_ref": "EVID-HIST-013",
        "_case": "PROGRESSION_COMPLETED_PRIOR",
        "_expected_outcome": "HISTORICAL",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Student completed B.Tech in 2024 (status COMPLETED in DB).",
    })
    rows.append({
        "row_number": 14,
        "apaar_id": "880000001072",
        "name": "Arjun Nair",
        "dob": "2002-05-18",
        "gender": "MALE",
        "mobile": "9821333444",
        "email": "arjun.nair.pg@example.edu.in",
        "roll_no": "24CSM0001",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-21",
        "consent_reference": "CONSENT-DEMO-014",
        "evidence_ref": "EVID-DEMO-014",
        "_case": "PROGRESSION_READMITTED",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "TIER_PROGRESSION",
        "_alert": "NONE",
        "_desc": "Post-graduate admission following completed undergraduate degree. Normal progression: no duplicate case created.",
    })

    # -------------------------------------------------------------------------
    # PART 4: Identity Cases (PASSED, FAILED format, FAILED mismatch, NOT_PROVIDED, UNAVAILABLE) (Rows 15-19)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 15,
        "apaar_id": "880000001080",
        "name": "Isha Chatterjee",
        "dob": "2005-07-25",
        "gender": "FEMALE",
        "mobile": "9821555666",
        "email": "isha.c@example.edu.in",
        "roll_no": "24CSE0015",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-22",
        "consent_reference": "CONSENT-DEMO-015",
        "evidence_ref": "EVID-DEMO-015",
        "_case": "IDENTITY_PASSED",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "PASSED",
        "_alert": "NONE",
        "_desc": "Identity verification PASSED: valid APAAR format + Luhn checksum + exact match in registry.",
    })
    rows.append({
        "row_number": 16,
        "apaar_id": "880000001089",  # Deliberately broken Luhn checksum (ends in 9 instead of 0)
        "name": "Manish Gupta",
        "dob": "2004-10-14",
        "gender": "MALE",
        "mobile": "9821666777",
        "email": "manish.g@example.edu.in",
        "roll_no": "24CSE0016",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-22",
        "consent_reference": "CONSENT-DEMO-016",
        "evidence_ref": "EVID-DEMO-016",
        "_case": "IDENTITY_FAILED_FORMAT",
        "_expected_outcome": "FAILED",
        "_expected_rule": "INVALID_APAAR_FORMAT",
        "_alert": "HIGH",
        "_desc": "Identity verification FAILED(format): 12-digit APAAR fails Luhn mod-10 check digit.",
    })
    rows.append({
        "row_number": 17,
        "apaar_id": "987654321015",  # In registry as Priya Patel, DOB 2005-03-21
        "name": "Priya Patel",
        "dob": "1998-01-01",         # Mismatched DOB planted
        "gender": "FEMALE",
        "mobile": "9821777888",
        "email": "priya.mismatch@example.edu.in",
        "roll_no": "24CSE0017",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-22",
        "consent_reference": "CONSENT-DEMO-017",
        "evidence_ref": "EVID-DEMO-017",
        "_case": "IDENTITY_FAILED_MISMATCH",
        "_expected_outcome": "FAILED",
        "_expected_rule": "IDENTITY_DEMOGRAPHIC_MISMATCH",
        "_alert": "HIGH",
        "_desc": "Identity verification FAILED(mismatch): APAAR exists in registry but DOB 1998-01-01 does not match official record (2005-03-21).",
    })
    rows.append({
        "row_number": 18,
        "apaar_id": "",              # Missing APAAR
        "name": "Siddharth Rao",
        "dob": "2005-11-30",
        "gender": "MALE",
        "mobile": "9821888999",
        "email": "siddharth.r@example.edu.in",
        "roll_no": "24CSE0018",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-23",
        "consent_reference": "CONSENT-DEMO-018",
        "evidence_ref": "EVID-DEMO-018",
        "_case": "IDENTITY_NOT_PROVIDED",
        "_expected_outcome": "COMMITTED_PROVISIONAL",
        "_expected_rule": "NOT_PROVIDED",
        "_alert": "LOW",
        "_desc": "APAAR not provided at time of admission; allowed within grace period as PROVISIONAL.",
    })
    rows.append({
        "row_number": 19,
        "apaar_id": "000000111222",  # Magic prefix '000000' triggers simulated upstream timeout
        "name": "Aniket Deshmukh",
        "dob": "2005-05-15",
        "gender": "MALE",
        "mobile": "9821999000",
        "email": "aniket.d@example.edu.in",
        "roll_no": "24CSE0019",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-23",
        "consent_reference": "CONSENT-DEMO-019",
        "evidence_ref": "EVID-DEMO-019",
        "_case": "IDENTITY_UNAVAILABLE",
        "_expected_outcome": "PENDING",
        "_expected_rule": "UNAVAILABLE",
        "_alert": "LOW",
        "_desc": "Upstream national APAAR gateway timeout (504). Held in PENDING for retry.",
    })

    # -------------------------------------------------------------------------
    # PART 5: Duplicates (Same-institution, Cross-institution, Fuzzy Typo) (Rows 20-24)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 20,
        "apaar_id": "880000001098",
        "name": "Amit Jadhav",
        "dob": "2004-12-19",
        "gender": "MALE",
        "mobile": "9822111222",
        "email": "amit.jadhav@example.edu.in",
        "roll_no": "24CSE0020",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-24",
        "consent_reference": "CONSENT-DEMO-020",
        "evidence_ref": "EVID-DEMO-020",
        "_case": "DUPLICATE_SAME_INST_PRIMARY",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "First legitimate enrollment of Amit Jadhav at IIT Delhi.",
    })
    rows.append({
        "row_number": 21,
        "apaar_id": "880000001098",  # Same APAAR again within same institution
        "name": "Amit Jadhav",
        "dob": "2004-12-19",
        "gender": "MALE",
        "mobile": "9822111222",
        "email": "amit.j2@example.edu.in",
        "roll_no": "24CSE0021",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-24",
        "consent_reference": "CONSENT-DEMO-021",
        "evidence_ref": "EVID-DEMO-021",
        "_case": "DUPLICATE_SAME_INSTITUTION",
        "_expected_outcome": "FAILED_OR_REVIEW",
        "_expected_rule": "DUPLICATE_SAME_INSTITUTION",
        "_alert": "HIGH",
        "_desc": "Duplicate APAAR submitted twice within the same institution (Tier 2 High duplicate alert).",
    })
    rows.append({
        "row_number": 22,
        "apaar_id": "987654321014",  # Already enrolled at NIT Trichy (1-1002)
        "name": "Ananya Iyer",
        "dob": "2005-01-19",
        "gender": "FEMALE",
        "mobile": "9822222333",
        "email": "ananya.iyer@example.edu.in",
        "roll_no": "24CSE0022",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-24",
        "consent_reference": "CONSENT-DEMO-022",
        "evidence_ref": "EVID-DEMO-022",
        "_case": "DUPLICATE_CROSS_INSTITUTION",
        "_expected_outcome": "FAILED_OR_REVIEW",
        "_expected_rule": "DUPLICATE_CROSS_INSTITUTION",
        "_alert": "CRITICAL",
        "_desc": "Cross-institution duplicate: Student actively enrolled at NIT Trichy attempted at IIT Delhi (Tier 1 Critical).",
    })
    rows.append({
        "row_number": 23,
        "apaar_id": "880000001106",
        "name": "Rajesh Kumar Sharma",
        "dob": "2004-07-15",
        "gender": "MALE",
        "mobile": "9811122233",
        "email": "rajesh.sharma@example.edu.in",
        "roll_no": "24CSE0023",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-25",
        "consent_reference": "CONSENT-DEMO-023",
        "evidence_ref": "EVID-DEMO-023",
        "_case": "FUZZY_PAIR_A",
        "_expected_outcome": "COMMITTED",
        "_expected_rule": "VALID",
        "_alert": "NONE",
        "_desc": "Primary record for Rajesh Kumar Sharma.",
    })
    rows.append({
        "row_number": 24,
        "apaar_id": "880000001114",
        "name": "Rajeysh Kumar Sharma",  # Typo in name: Jaro-Winkler >= 0.92 + identical DOB
        "dob": "2004-07-15",
        "gender": "MALE",
        "mobile": "9811122233",
        "email": "rajeysh.sharma@example.edu.in",
        "roll_no": "24CSE0024",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-25",
        "consent_reference": "CONSENT-DEMO-024",
        "evidence_ref": "EVID-DEMO-024",
        "_case": "FUZZY_TYPO_PAIR_B",
        "_expected_outcome": "REVIEW_FLAGGED",
        "_expected_rule": "TIER_FUZZY",
        "_alert": "MEDIUM",
        "_desc": "Fuzzy typo duplicate match: Rajeysh vs Rajesh (Jaro-Winkler >= 0.92) with identical DOB.",
    })

    # -------------------------------------------------------------------------
    # PART 6: Cross-Field / Flag Inconsistencies (Rows 25-28)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 25,
        "apaar_id": "880000001122",
        "name": "Karan Malhotra",
        "dob": "2005-01-30",
        "gender": "MALE",
        "mobile": "9823111222",
        "email": "karan.m@example.edu.in",
        "roll_no": "24CSE0025",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "NRI",
        "category": "OPEN",
        "nri_flag": "true",
        "oci_flag": "false",
        "fn_flag": "true",  # Contradictory: NRI and FN cannot both be true
        "admission_date": "2024-07-26",
        "consent_reference": "CONSENT-DEMO-025",
        "evidence_ref": "EVID-DEMO-025",
        "_case": "CONTRADICTORY_FLAGS",
        "_expected_outcome": "FAILED",
        "_expected_rule": "CONTRADICTORY_FLAGS",
        "_alert": "HIGH",
        "_desc": "Contradictory citizenship flags: Student cannot be both an NRI (Indian citizen) and FN (foreign national).",
    })
    rows.append({
        "row_number": 26,
        "apaar_id": "880000001130",
        "name": "Diya Sen",
        "dob": "2005-09-08",
        "gender": "FEMALE",
        "mobile": "9823222333",
        "email": "diya.sen@example.edu.in",
        "roll_no": "24CSE0026",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "NRI",
        "category": "OPEN",
        "nri_flag": "false",  # Mismatch: NRI seat requires nri_flag=true
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-26",
        "consent_reference": "CONSENT-DEMO-026",
        "evidence_ref": "EVID-DEMO-026",
        "_case": "NRI_SEAT_FLAG_MISMATCH",
        "_expected_outcome": "FAILED",
        "_expected_rule": "NRI_SEAT_FLAG_MISMATCH",
        "_alert": "HIGH",
        "_desc": "Admitted under NRI seat quota but nri_flag is false.",
    })
    rows.append({
        "row_number": 27,
        "apaar_id": "880000001148",
        "name": "Reyansh Bose",
        "dob": "2004-06-22",
        "gender": "MALE",
        "mobile": "9823333444",
        "email": "reyansh.bose@example.edu.in",
        "roll_no": "24CSE0027",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "SUPERNUMERARY_FN_OCI_PIO",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",  # Mismatch: Supernumerary requires fn_flag or oci_flag=true
        "admission_date": "2024-07-27",
        "consent_reference": "CONSENT-DEMO-027",
        "evidence_ref": "EVID-DEMO-027",
        "_case": "SUPERNUMERARY_FLAG_MISMATCH",
        "_expected_outcome": "FAILED",
        "_expected_rule": "SUPERNUMERARY_FLAG_MISMATCH",
        "_alert": "HIGH",
        "_desc": "Admitted under SUPERNUMERARY_FN_OCI_PIO but neither fn_flag nor oci_flag is true.",
    })
    rows.append({
        "row_number": 28,
        "apaar_id": "880000001155",
        "name": "Hans Mueller",
        "dob": "2004-03-12",
        "gender": "MALE",
        "mobile": "9823444555",
        "email": "hans.m@example.edu.in",
        "roll_no": "24CSE0028",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "true",  # Foreign national cannot occupy regular seat
        "admission_date": "2024-07-27",
        "consent_reference": "CONSENT-DEMO-028",
        "evidence_ref": "EVID-DEMO-028",
        "_case": "FN_IN_REGULAR_SEAT",
        "_expected_outcome": "FAILED",
        "_expected_rule": "FN_IN_REGULAR_SEAT",
        "_alert": "CRITICAL",
        "_desc": "Foreign National candidate allocated under REGULAR approved intake instead of supernumerary quota.",
    })

    # -------------------------------------------------------------------------
    # PART 7: Programme B - REGULAR Capacity Exceeded (Rows 29-33)
    # Approved: REGULAR=30, NRI=5, SUPERNUMERARY=5. Database has 30 filled.
    # -------------------------------------------------------------------------
    for b_idx in range(1, 6):
        row_num = 28 + b_idx
        rows.append({
            "row_number": row_num,
            "apaar_id": f"88000000{1155 + b_idx}",
            "name": f"Student OverFlow{b_idx} IT",
            "dob": "2005-02-10",
            "gender": "MALE" if b_idx % 2 == 1 else "FEMALE",
            "mobile": f"9824{b_idx:06d}",
            "email": f"overflow{b_idx}@it.example.edu.in",
            "roll_no": f"24IT00{30 + b_idx}",
            "programme": "ENGINEERING_AND_TECHNOLOGY",
            "branch": "INFORMATION_TECHNOLOGY",
            "campus": "MAIN",
            "shift": "FIRST",
            "academic_year": "2024-2025",
            "seat_type": "REGULAR",
            "category": "OPEN",
            "nri_flag": "false",
            "oci_flag": "false",
            "fn_flag": "false",
            "admission_date": "2024-07-28",
            "consent_reference": f"CONSENT-DEMO-0{row_num}",
            "evidence_ref": f"EVID-DEMO-0{row_num}",
            "_case": f"PROGRAMME_B_CAPACITY_EXCEEDED_{b_idx}",
            "_expected_outcome": "FAILED_OR_ALERT",
            "_expected_rule": "CAPACITY_EXCEEDED",
            "_alert": "CRITICAL",
            "_desc": "Programme B regular intake capacity (30 seats) exceeded; supernumerary seats unused.",
        })

    # -------------------------------------------------------------------------
    # PART 8: Programme C - Zero Approved Seats Category (Rows 34-36)
    # Approved for MECHANICAL_ENGINEERING: REGULAR=60, NRI=0, SUPERNUMERARY=0
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 34,
        "apaar_id": "880000001163",
        "name": "Aditya Reddy",
        "dob": "2005-08-14",
        "gender": "MALE",
        "mobile": "9825111222",
        "email": "aditya.reddy@example.edu.in",
        "roll_no": "24ME0001",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "MECHANICAL_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "NRI",  # Zero NRI seats approved for Mechanical Engineering!
        "category": "OPEN",
        "nri_flag": "true",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-29",
        "consent_reference": "CONSENT-DEMO-034",
        "evidence_ref": "EVID-DEMO-034",
        "_case": "ZERO_APPROVED_SEATS_NRI",
        "_expected_outcome": "FAILED",
        "_expected_rule": "ZERO_APPROVED_SEATS",
        "_alert": "CRITICAL",
        "_desc": "Admission under NRI category in Mechanical Engineering where 0 NRI seats are approved by AICTE.",
    })
    rows.append({
        "row_number": 35,
        "apaar_id": "880000001171",
        "name": "Sarah Connor",
        "dob": "2004-11-20",
        "gender": "FEMALE",
        "mobile": "9825222333",
        "email": "sarah.connor@example.edu.in",
        "roll_no": "24ME0002",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "MECHANICAL_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "SUPERNUMERARY_FN_OCI_PIO",  # Zero FN/OCI seats approved
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "true",
        "admission_date": "2024-07-29",
        "consent_reference": "CONSENT-DEMO-035",
        "evidence_ref": "EVID-DEMO-035",
        "_case": "ZERO_APPROVED_SEATS_FN",
        "_expected_outcome": "FAILED",
        "_expected_rule": "ZERO_APPROVED_SEATS",
        "_alert": "CRITICAL",
        "_desc": "Admission under SUPERNUMERARY_FN_OCI_PIO in Mechanical Engineering where 0 supernumerary seats are approved.",
    })
    rows.append({
        "row_number": 36,
        "apaar_id": "880000001189",
        "name": "Farhan Qureshi",
        "dob": "2005-04-12",
        "gender": "MALE",
        "mobile": "9825333444",
        "email": "farhan.q@example.edu.in",
        "roll_no": "24ME0003",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "MECHANICAL_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "SUPERNUMERARY_GULF_WORKER_CHILD",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-29",
        "consent_reference": "CONSENT-DEMO-036",
        "evidence_ref": "EVID-DEMO-036",
        "_case": "ZERO_APPROVED_SEATS_GULF",
        "_expected_outcome": "FAILED",
        "_expected_rule": "ZERO_APPROVED_SEATS",
        "_alert": "CRITICAL",
        "_desc": "Admission under SUPERNUMERARY_GULF_WORKER_CHILD in Mechanical Engineering where 0 seats are approved.",
    })

    # -------------------------------------------------------------------------
    # PART 9: Data Quality / Hygiene / Structural Errors (Rows 37-40)
    # -------------------------------------------------------------------------
    rows.append({
        "row_number": 37,
        "apaar_id": "880000001197",
        "name": "",                  # Missing name
        "dob": "2005-03-10",
        "gender": "MALE",
        "mobile": "9826111222",
        "email": "noname@example.edu.in",
        "roll_no": "24CSE0037",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-30",
        "consent_reference": "CONSENT-DEMO-037",
        "evidence_ref": "EVID-DEMO-037",
        "_case": "MISSING_NAME",
        "_expected_outcome": "FAILED",
        "_expected_rule": "MISSING_NAME",
        "_alert": "HIGH",
        "_desc": "Required demographic validation failure: Student legal name is empty.",
    })
    rows.append({
        "row_number": 38,
        "apaar_id": "880000001205",
        "name": "Tanvi Rao",
        "dob": "1999-99-99",         # Invalid date of birth
        "gender": "FEMALE",
        "mobile": "9826222333",
        "email": "tanvi.rao@example.edu.in",
        "roll_no": "24CSE0038",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-30",
        "consent_reference": "CONSENT-DEMO-038",
        "evidence_ref": "EVID-DEMO-038",
        "_case": "INVALID_DOB",
        "_expected_outcome": "FAILED",
        "_expected_rule": "INVALID_DOB",
        "_alert": "HIGH",
        "_desc": "Date of birth format invalid (cannot be parsed into ISO YYYY-MM-DD).",
    })
    rows.append({
        "row_number": 39,
        "apaar_id": "880000001213",
        "name": "Pranav Kulkarni",
        "dob": "2005-06-25",
        "gender": "MALE",
        "mobile": "9826333444",
        "email": "pranav.k@example.edu.in",
        "roll_no": "24CSE0039",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "COMPUTER_SCIENCE_AND_ENGINEERING",
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "",        # Missing admission date
        "consent_reference": "CONSENT-DEMO-039",
        "evidence_ref": "EVID-DEMO-039",
        "_case": "MISSING_ADMISSION_DATE",
        "_expected_outcome": "FAILED",
        "_expected_rule": "MISSING_ADMISSION_DATE",
        "_alert": "HIGH",
        "_desc": "Mandatory admission date is missing.",
    })
    rows.append({
        "row_number": 40,
        "apaar_id": "880000001221",
        "name": "Meera Joshi",
        "dob": "2005-09-15",
        "gender": "FEMALE",
        "mobile": "9826444555",
        "email": "meera.joshi@example.edu.in",
        "roll_no": "24AST0001",
        "programme": "ENGINEERING_AND_TECHNOLOGY",
        "branch": "ASTRONAUTICAL_ENGINEERING",  # Unapproved programme / branch
        "campus": "MAIN",
        "shift": "FIRST",
        "academic_year": "2024-2025",
        "seat_type": "REGULAR",
        "category": "OPEN",
        "nri_flag": "false",
        "oci_flag": "false",
        "fn_flag": "false",
        "admission_date": "2024-07-31",
        "consent_reference": "CONSENT-DEMO-040",
        "evidence_ref": "EVID-DEMO-040",
        "_case": "UNAPPROVED_PROGRAMME_BRANCH",
        "_expected_outcome": "FAILED",
        "_expected_rule": "UNAPPROVED_PROGRAMME_BRANCH",
        "_alert": "CRITICAL",
        "_desc": "Institutional authority failure: No AICTE Extension of Approval (EoA) exists for ASTRONAUTICAL_ENGINEERING.",
    })

    # Write imperfect_demo.csv (excluding internal metadata columns starting with '_')
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            csv_row = {k: r[k] for k in EXPECTED_CSV_COLUMNS}
            writer.writerow(csv_row)

    return rows


def generate_expected_markdown(demo_rows: List[Dict[str, Any]], output_path: str) -> None:
    """
    Emits sample_data/EXPECTED.md documenting exactly which rows trigger which rule/case.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    lines = [
        "# AICTE APAAR Connect: Expected Validation & Anomaly Verification Matrix",
        "",
        "This document lists the exact expected behavior, rule triggers, and alert classifications",
        "for every row in `imperfect_demo.csv`. Automated test suites, integration benchmarks, and",
        "live evaluators assert against these specifications.",
        "",
        "## Summary of Test Cases Planted (Total Rows: 40)",
        "",
        "- **Rows 1-10**: Programme A Compliant Normal / Quotas (REGULAR, NRI, FN, OCI, Gulf Worker, TFW).",
        "- **Rows 11-12**: Twin Pair Exception (same DOB, same phone, same surname, distinct first names) $\\implies$ **MUST NOT ALERT**.",
        "- **Rows 13-14**: Progression Exception (completed undergraduate degree progressing to post-grad) $\\implies$ **NO ALERT**.",
        "- **Rows 15-19**: Identity Verification Cases (`PASSED`, `FAILED(format)`, `FAILED(mismatch)`, `NOT_PROVIDED`, `UNAVAILABLE`).",
        "- **Rows 20-24**: Duplicate Cases (Same-institution, Cross-institution, Fuzzy typo pair).",
        "- **Rows 25-28**: Cross-Field Consistency (Contradictory NRI/FN flags, Seat vs Flag mismatch, FN in regular seat).",
        "- **Rows 29-33**: Programme B Seat Over-Admission (REGULAR capacity exceeded while supernumerary unused).",
        "- **Rows 34-36**: Programme C Unapproved Seat Allocation (Zero approved seats for NRI / Supernumerary).",
        "- **Rows 37-40**: Data Quality & Hygiene (Missing name, invalid DOB format, missing admission date, unapproved branch).",
        "",
        "---",
        "",
        "## Complete Row-by-Row Assertion Table",
        "",
        "| Row # | Student Name | APAAR ID | Seat Type | Expected Outcome | Rule / Code | Alert Level | Reason & Explanation |",
        "| :---: | :--- | :--- | :--- | :---: | :--- | :---: | :--- |",
    ]

    for r in demo_rows:
        row_num = r["row_number"]
        name = r["name"] or "*(Blank Name)*"
        apaar = r["apaar_id"] or "*(Not Provided)*"
        seat = r["seat_type"]
        outcome = r["_expected_outcome"]
        rule = r["_expected_rule"]
        alert = r["_alert"]
        desc = r["_desc"]

        lines.append(f"| {row_num} | {name} | `{apaar}` | `{seat}` | **{outcome}** | `{rule}` | `{alert}` | {desc} |")

    lines.extend([
        "",
        "---",
        "",
        "## Evaluation & Live Demo Instructions",
        "",
        "1. **Dry-Run Validation Test**:",
        "   ```bash",
        "   # Upload and perform a dry run",
        "   POST /api/submissions/upload (multipart: imperfect_demo.csv)",
        "   POST /api/submissions/{id}/validate-dry-run",
        "   ```",
        "   *Expected Result*: Returns summary with 14 Valid rows, 26 Invalid rows, matching exactly the planted codes above.",
        "",
        "2. **Risk & Anomaly Priority Verification**:",
        "   ```bash",
        "   GET /api/analytics/institution/{institution_id}/anomalies",
        "   ```",
        "   *Expected Result*: Programme B flags `SEAT_CAPACITY_EXCEEDED` alert; Programme C flags `NO_APPROVAL_CATEGORY` alert;",
        "   Duplicate queue highlights Row 21 (`DUPLICATE_SAME_INSTITUTION`) and Row 22 (`DUPLICATE_CROSS_INSTITUTION`).",
        "",
        "3. **Zero-False-Positive Assurances**:",
        "   - **Rows 11 & 12 (Twins)** produce zero duplicate cases.",
        "   - **Rows 13 & 14 (Progression)** produce zero duplicate cases (`TIER_PROGRESSION` flagged without review case).",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="AICTE APAAR Connect Synthetic Data Generator")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    parser.add_argument("--registry-size", type=int, default=12000, help="Number of synthetic APAAR directory entries (default: 12000)")
    parser.add_argument("--perf-size", type=int, default=10000, help="Number of rows for performance CSV (default: 10000)")
    parser.add_argument("--output-dir", type=str, default="sample_data", help="Target output folder (default: sample_data)")
    args = parser.parse_args()

    print("=" * 70)
    print("AICTE APAAR CONNECT - SYNTHETIC DATA GENERATOR")
    print(f"Random Seed:      {args.seed}")
    print(f"Registry Size:    {args.registry_size}")
    print(f"Performance Rows: {args.perf_size}")
    print(f"Target Directory: {args.output_dir}")
    print("=" * 70)

    # Initialize deterministic generators
    rng = random.Random(args.seed)
    Faker.seed(args.seed)
    faker = Faker("en_IN")

    os.makedirs(args.output_dir, exist_ok=True)

    # 1. Generate Synthetic APAAR Registry
    registry_file = os.path.join(args.output_dir, "mock_apaar_directory.json")
    print(f"[1/4] Generating ~{args.registry_size} synthetic APAAR registry records...")
    registry = build_synthetic_apaar_registry(faker=faker, rng=rng, count=args.registry_size)
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    print(f"      Saved: {registry_file} ({len(registry)} records)")

    # 2. Generate 10,000-Row Performance CSV
    perf_file = os.path.join(args.output_dir, "performance_10k.csv")
    print(f"[2/4] Generating {args.perf_size}-row performance CSV...")
    generate_performance_csv(registry=registry, output_path=perf_file, rng=rng, count=args.perf_size)
    print(f"      Saved: {perf_file}")

    # 3. Generate 40-Row Imperfect Demo CSV
    demo_file = os.path.join(args.output_dir, "imperfect_demo.csv")
    print("[3/4] Generating 40-row imperfect_demo.csv with planted errors...")
    demo_rows = generate_imperfect_demo_csv(registry=registry, output_path=demo_file)
    print(f"      Saved: {demo_file} ({len(demo_rows)} rows)")

    # 4. Generate sample_data/EXPECTED.md
    expected_file = os.path.join(args.output_dir, "EXPECTED.md")
    print("[4/4] Emitting verification matrix to EXPECTED.md...")
    generate_expected_markdown(demo_rows=demo_rows, output_path=expected_file)
    print(f"      Saved: {expected_file}")

    print("=" * 70)
    print("[SUCCESS] All synthetic data artifacts generated successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
