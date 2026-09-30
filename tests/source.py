#!/usr/bin/env python3
"""Direct-source import and export-surface tests for the jq package."""
import os
import shutil
import subprocess
import sys

NIFT = sys.argv[1] if len(sys.argv) > 1 else "nift"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "tests", ".source-work")


def invoke(name, source, extra_args=()):
    path = os.path.join(WORK, name)
    with open(path, "w", encoding="utf-8") as output:
        output.write(source)
    return subprocess.run(
        [NIFT, name, *extra_args], cwd=WORK, capture_output=True, text=True
    )


try:
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    source_path = os.path.join(ROOT, "src", "jq.f").replace("\\", "/")
    direct = invoke(
        "direct.f",
        f'@import("{source_path}")\nprint(jq.capabilities().text_output)\n',
    )
    expected = ["true"]
    if direct.returncode != 0 or direct.stdout.strip().splitlines() != expected:
        raise AssertionError("direct source import failed: " + direct.stdout + direct.stderr)

    private_cases = {
        "private-method.f": f'@import("{source_path}")\nprint(jq.process_available())\n',
        "private-global.f": f'@import("{source_path}")\nprint(jq_backend_requested)\n',
        "unexported-type.f": f'@import("{source_path}")\nprint(type(jq_backend_selected))\n',
    }
    for name, source in private_cases.items():
        result = invoke(name, source)
        if result.returncode == 0:
            raise AssertionError(f"private package symbol leaked: {name}")

    disabled = invoke(
        "disabled.f",
        f'@import("{source_path}")\nprint(jq.available())\nr := jq.run("{{}}", ".")\nprint(r.error_code)\n',
        ("--no-process",),
    )
    if disabled.returncode != 0 or disabled.stdout.strip().splitlines() != ["false", "backend_unavailable"]:
        raise AssertionError("direct --no-process recovery failed: " + disabled.stdout + disabled.stderr)
    print("PASS jq source tests")
finally:
    shutil.rmtree(WORK, ignore_errors=True)
