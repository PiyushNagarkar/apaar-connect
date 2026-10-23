#!/usr/bin/env python3
"""
Verify Audit Hash Chain Script (apaar-connect/backend/scripts/verify_audit_chain.py).

Verifies the cryptographic integrity of append-only audit events stored in the database.
Computes:
  hash = SHA256(prev_hash + canonical_event)
and verifies that row[i].prev_hash matches row[i-1].hash.

Exits with:
  0: Integrity check PASSED (chain intact)
  1: Integrity check FAILED (tampering or broken chain detected)
"""
import argparse
import os
import sys

# Ensure backend package can be imported
_curr_dir = os.path.abspath(os.path.dirname(__file__))
_backend_dir = os.path.abspath(os.path.join(_curr_dir, ".."))
_apaar_dir = os.path.abspath(os.path.join(_backend_dir, ".."))
_root_dir = os.path.abspath(os.path.join(_apaar_dir, ".."))

for p in (_root_dir, _backend_dir, _apaar_dir):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from backend.database import SessionLocal
from backend.services.audit_service import verify_audit_hash_chain


def main():
    parser = argparse.ArgumentParser(description="Cryptographically verify APAAR Connect audit hash chain.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of events to verify (default: all)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed validation logs")
    args = parser.parse_args()

    print("=" * 70)
    print("AICTE APAAR-CONNECT - AUDIT LOG CRYPTOGRAPHIC INTEGRITY VERIFIER")
    print("=" * 70)

    db = SessionLocal()
    try:
        report = verify_audit_hash_chain(db=db, limit=args.limit)

        print(f"Total Audit Events Checked: {report['total_events_checked']}")
        print(f"Genesis Root Hash:          {report['genesis_hash'] or 'N/A'}")
        print(f"Chain Tail Hash:            {report['tail_hash'] or 'N/A'}")
        print("-" * 70)

        if report["chain_valid"]:
            print("[SUCCESS] ALL AUDIT CHAIN HASH LINKS ARE VALID AND UNBROKEN.")
            print("Cryptographic guarantee: No audit events have been modified, deleted, or inserted.")
            print("=" * 70)
            sys.exit(0)
        else:
            print("[CRITICAL ALERT] AUDIT CHAIN TAMPERING DETECTED!")
            print(f"Number of broken links / tampered events: {len(report['broken_links'])}")
            for idx, bl in enumerate(report["broken_links"], 1):
                print(f"  {idx}. Event Index: {bl.get('event_index')}, Event ID: {bl.get('event_id')}")
                print(f"     Issue: {bl.get('issue')}")
                if "expected_hash" in bl:
                    print(f"     Expected Hash: {bl.get('expected_hash')}")
                    print(f"     Stored Hash:   {bl.get('stored_hash')}")
                if "expected_prev_hash" in bl:
                    print(f"     Expected Prev: {bl.get('expected_prev_hash')}")
                    print(f"     Actual Prev:   {bl.get('actual_prev_hash')}")
            print("=" * 70)
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
