#!/usr/bin/env python3
"""Installed external-consumer integration tests against the real jq CLI."""
import json
import os
import shutil
import subprocess
import sys

NIFT = sys.argv[1] if len(sys.argv) > 1 else "nift"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "tests", ".integration-work")

if shutil.which("jq") is None:
    print("UNAVAILABLE real jq integration: jq executable not found")
    raise SystemExit(0)


def invoke(name, source, *, env=None, extra_args=()):
    path = os.path.join(WORK, name)
    with open(path, "w", encoding="utf-8") as output:
        output.write(source)
    return subprocess.run(
        [NIFT, name, *extra_args], cwd=WORK, env=env,
        capture_output=True, text=True,
    )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


try:
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(os.path.join(WORK, ".nift"))
    subprocess.run([NIFT, "add", ROOT], cwd=WORK, check=True, capture_output=True)

    input_path = os.path.join(WORK, "input spaces ' quoted.json")
    with open(input_path, "w", encoding="utf-8") as output:
        json.dump({"name": "Nift", "items": [1, 2], "unicode": "héllo 世界"}, output, ensure_ascii=False)

    injection_marker = os.path.join(WORK, "INJECTION_MARKER")
    large_text = "x" * 300000
    script = r'''
@import("jq")
print(jq.available())
print(jq.backends().join(","))
print(jq.backend())
print(jq.version())
print(jq.use_backend("ffi").error_code)
print(jq.use_backend("bogus").error_code)
print(jq.use_backend("process").ok)
print(jq.capabilities().raw)
identity := jq.run("{\"a\":1}", ".")
print(identity.ok)
print(identity.stdout.trim())
print(jq.run("{\"name\":\"Nift\"}", ".name", {"raw":true}).stdout.trim())
print(jq.run("{\"compact\":true}", ".", {"compact":true}).stdout.trim())
print(jq.query("{\"items\":[1,2]}", ".items[]", {"compact":true}).stdout.trim().replace("\n", ","))
print(jq.run("1\n2\n3\n", "add", {"slurp":true,"compact":true}).stdout.trim())
bad_filter := jq.run("{}", ".[")
print(bad_filter.ok)
print(bad_filter.error_code)
print(bad_filter.exit_code != 0)
bad_json := jq.run("{bad", ".")
print(bad_json.error_code)
print(bad_json.stderr != "")
print(jq.run("{}", "empty").stdout == "")
nonzero := jq.run("null", ".", {"extra_args":["--exit-status"]})
print(nonzero.error_code)
print(nonzero.exit_code != 0)
print(jq.run("{}", ".", {"raw":"yes"}).error_code)
print(jq.run("{}", ".", {"unknown":true}).error_code)
print(jq.run("{}", ".", {"extra_args":[1]}).error_code)
print(jq.file(INPUT_PATH, ".unicode", {"raw":true}).stdout.trim())
print(jq.file(INPUT_PATH, ".name", {"raw":true,"extra_args":["--exit-status"]}).stdout.trim())
quoted := jq.run("{\"text\":\"spaces ' and \\\"quotes\\\"; $(touch INJECTION_MARKER)\"}", ".text", {"raw":true})
print(quoted.stdout.trim())
argv_safe := jq.run("{}", "$value", {"raw":true,"extra_args":["--arg","value","$(touch INJECTION_MARKER)"]})
print(argv_safe.stdout.trim())
print(jq.run(LARGE_JSON, ".payload | length", {"raw":true}).stdout.trim())
print(jq.use_backend("auto").error_code)
'''.replace("INPUT_PATH", json.dumps(input_path)).replace("INJECTION_MARKER", injection_marker).replace("LARGE_JSON", json.dumps(json.dumps({"payload": large_text})))
    result = invoke("consumer.f", script)
    lines = result.stdout.strip().splitlines()
    require(result.returncode == 0, result.stdout + result.stderr)
    require(lines[0:3] == ["true", "process", "process"], str(lines))
    require(lines[3].startswith("jq-"), "unexpected jq version: " + lines[3])
    expected_tail = [
        "backend_unavailable", "unknown_backend", "true", "true", "true",
        "{", '  "a": 1', "}", "Nift", '{"compact":true}', "1,2", "6", "false", "process_failed",
        "true", "process_failed", "true", "true", "process_failed", "true",
        "invalid_options", "invalid_options", "invalid_options", "héllo 世界", "Nift",
        "spaces ' and \"quotes\"; $(touch " + injection_marker + ")",
        "$(touch " + injection_marker + ")",
        "300000", "backend_locked",
    ]
    require(lines[4:] == expected_tail, "integration mismatch\n" + result.stdout + result.stderr)
    require(not os.path.exists(injection_marker), "shell injection marker was created")

    missing_dir = os.path.join(WORK, "missing-path")
    os.makedirs(missing_dir)
    missing = invoke(
        "missing.f",
        '@import("jq")\nprint(jq.available())\nprint(jq.backends().size())\nr := jq.run("{}", ".")\nprint(r.error_code)\nprint(r.exit_code)\n',
        env={**os.environ, "PATH": missing_dir},
    )
    require(
        missing.returncode == 0 and missing.stdout.strip().splitlines() == ["false", "0", "backend_unavailable", "127"],
        "missing executable recovery failed: " + missing.stdout + missing.stderr,
    )

    disabled = invoke(
        "disabled.f",
        '@import("jq")\nprint(jq.available())\nprint(jq.run("{}", ".").error_code)\n',
        extra_args=("--no-process",),
    )
    require(
        disabled.returncode == 0 and disabled.stdout.strip().splitlines() == ["false", "backend_unavailable"],
        "--no-process recovery failed: " + disabled.stdout + disabled.stderr,
    )

    disabled_env = invoke(
        "disabled-env.f",
        '@import("jq")\nprint(jq.available())\nprint(jq.file("never-read.json", ".").error_code)\n',
        env={**os.environ, "NIFT_NO_PROCESS": "1"},
    )
    require(
        disabled_env.returncode == 0 and disabled_env.stdout.strip().splitlines() == ["false", "backend_unavailable"],
        "NIFT_NO_PROCESS recovery failed: " + disabled_env.stdout + disabled_env.stderr,
    )

    jq_path = shutil.which("jq")
    require(jq_path is not None, "real jq executable is required")
    jq_only = os.path.join(WORK, "jq-only-path")
    os.makedirs(jq_only)
    exposed_jq = os.path.join(jq_only, "jq.exe" if os.name == "nt" else "jq")
    try:
        os.symlink(jq_path, exposed_jq)
    except (OSError, NotImplementedError):
        shutil.copy2(jq_path, exposed_jq)
    no_secure_temp = invoke(
        "no-secure-temp.f",
        '@import("jq")\nr := jq.run("{\\"fallback\\":true}", ".fallback", {"raw":true})\nprint(r.ok)\nprint(r.error_code)\nprint(r.exit_code == null)\n',
        env={**os.environ, "PATH": jq_only, "TMPDIR": WORK, "TEMP": WORK, "TMP": WORK},
    )
    require(
        no_secure_temp.returncode == 0 and no_secure_temp.stdout.strip().splitlines() == ["false", "temporary_file", "true"],
        "secure temporary fail-closed behavior failed: " + no_secure_temp.stdout + no_secure_temp.stderr,
    )

    leftovers = [name for name in os.listdir(WORK) if name.startswith(".nift-jq-")]
    require(not leftovers, "temporary files leaked: " + repr(leftovers))
    print("PASS jq integration tests")
finally:
    shutil.rmtree(WORK, ignore_errors=True)
