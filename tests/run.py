#!/usr/bin/env python3
"""Run the source and installed-consumer jq package suites."""
import os
import subprocess
import sys

NIFT = sys.argv[1] if len(sys.argv) > 1 else "nift"
ROOT = os.path.dirname(os.path.abspath(__file__))

for suite in ("source.py", "deterministic.py", "integration.py"):
    subprocess.run([sys.executable, os.path.join(ROOT, suite), NIFT], check=True)

print("PASS all jq tests")
