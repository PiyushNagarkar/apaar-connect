#!/usr/bin/env python3
"""
Verify Audit Hash Chain Script (scripts/verify_audit_chain.py).
Re-exports and runs apaar-connect/backend/scripts/verify_audit_chain.py.
"""
import os
import sys

_curr_dir = os.path.abspath(os.path.dirname(__file__))
_root_dir = os.path.abspath(os.path.join(_curr_dir, ".."))
_apaar_dir = os.path.join(_root_dir, "apaar-connect")
_backend_dir = os.path.join(_apaar_dir, "backend")

for p in (_root_dir, _backend_dir, _apaar_dir):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from backend.scripts.verify_audit_chain import main

if __name__ == "__main__":
    main()
