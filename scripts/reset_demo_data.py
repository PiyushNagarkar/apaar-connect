#!/usr/bin/env python3
"""
Reset Demo Data Script (scripts/reset_demo_data.py).

Cleans the existing database tables completely and re-seeds with a fresh,
deterministic demonstration state using scripts/seed_demo_data.py.

Usage:
  python scripts/reset_demo_data.py [--seed 42]
"""
import argparse
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

from backend.database import Base, engine, SessionLocal
from scripts.seed_demo_data import (
    DEMO_PASSWORD_PLAIN,
    seed_institutions,
    seed_demo_users,
    seed_programmes_and_seat_matrices,
    seed_demo_scenarios,
)
from faker import Faker
import random


def reset_and_seed_database(seed: int = 42) -> None:
    print("=" * 70)
    print("AICTE APAAR CONNECT - RESET & RE-SEED DEMO ENVIRONMENT")
    print(f"Random Seed:   {seed}")
    print(f"Demo Password: {DEMO_PASSWORD_PLAIN}")
    print("=" * 70)

    print("[1/3] Dropping existing database tables...")
    try:
        Base.metadata.drop_all(bind=engine)
        print("      Existing tables dropped cleanly.")
    except Exception as e:
        print(f"      Warning during drop_all: {e}")

    print("[2/3] Re-creating fresh schema...")
    Base.metadata.create_all(bind=engine)
    print("      Fresh schema created.")

    print("[3/3] Populating deterministic demonstration dataset...")
    rng = random.Random(seed)
    Faker.seed(seed)
    faker = Faker("en_IN")

    db = SessionLocal()
    try:
        inst_map = seed_institutions(db)
        user_map = seed_demo_users(db, inst_map)
        approvals = seed_programmes_and_seat_matrices(db, inst_map)
        seed_demo_scenarios(
            db=db,
            inst_map=inst_map,
            approvals=approvals,
            user_map=user_map,
            faker=faker,
            rng=rng,
        )
        print("=" * 70)
        print("[SUCCESS] Database reset and demo environment initialized successfully!")
        print("=" * 70)
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Re-seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="AICTE APAAR Connect Demo Database Reset & Seeder")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    args = parser.parse_args()

    reset_and_seed_database(seed=args.seed)


if __name__ == "__main__":
    main()
