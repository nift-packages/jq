#!/usr/bin/env python3
"""Deterministic jq facade tests using a logged fake executable."""
import json
import os
import shutil
import stat
import subprocess
import sys

NIFT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "nift")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "tests", ".deterministic-work")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


try:
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(os.path.join(WORK, ".nift"))
    fake_bin = os.path.join(WORK, "fake bin")
    temp_dir = os.path.join(WORK, "temp space")
    os.makedirs(fake_bin)
    os.makedirs(temp_dir)
    log_path = os.path.join(WORK, "argv.jsonl")
    fake_source = r'''import json
import os
import sys

args = sys.argv[1:]
if args == ["--version"]:
    print("jq-fixture-1.0")
    raise SystemExit(0)
if "--" not in args or len(args) < 3:
    print("missing operand separator", file=sys.stderr)
    raise SystemExit(90)
expression = args[-2]
input_path = args[-1]
with open(input_path, encoding="utf-8") as source:
    text = source.read()
with open(os.environ["JQ_FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "input": text}, separators=(",", ":")) + "\n")
if expression == ".[":
    print("fixture filter error", file=sys.stderr)
    raise SystemExit(3)
try:
    value = json.loads(text)
except json.JSONDecodeError:
    print("fixture JSON error", file=sys.stderr)
    raise SystemExit(4)
if expression.startswith(".") and isinstance(value, dict) and expression[1:] in value:
    value = value[expression[1:]]
elif expression == "$value" and "--arg" in args:
    value = args[args.index("--arg") + 2]
raw = "--raw-output" in args
compact = "--compact-output" in args
if raw and isinstance(value, (str, int, float, bool)):
    print(str(value).lower() if isinstance(value, bool) else value)
else:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":") if compact else None))
'''
    if os.name == "nt":
        fixture = os.path.join(fake_bin, "jq_fixture.py")
        with open(fixture, "w", encoding="utf-8") as handle:
            handle.write(fake_source)
        fake = os.path.join(fake_bin, "jq.cmd")
        with open(fake, "w", encoding="utf-8", newline="") as handle:
            handle.write(f'@echo off\r\n@"{sys.executable}" "%~dp0jq_fixture.py" %*\r\n')
    else:
        fake = os.path.join(fake_bin, "jq")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(f"#!{sys.executable}\n" + fake_source)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
    subprocess.run([NIFT, "add", ROOT], cwd=WORK, check=True, capture_output=True)

    base_env = {
        **os.environ,
        "PATH": fake_bin + os.pathsep + os.environ.get("PATH", ""),
        "TMPDIR": temp_dir,
        "TEMP": temp_dir,
        "TMP": temp_dir,
        "JQ_FAKE_LOG": log_path,
    }

    def invoke(name, source, *, env=base_env, extra_args=()):
        path = os.path.join(WORK, name)
        with open(path, "w", encoding="utf-8") as output:
            output.write(source)
        return subprocess.run(
            [NIFT, name, *extra_args], cwd=WORK, env=env,
            capture_output=True, text=True,
        )

    input_path = os.path.join(WORK, "input spaces; $(not-shell).json")
    with open(input_path, "w", encoding="utf-8") as output:
        json.dump({"name": "Nift"}, output)
    marker = os.path.join(WORK, "INJECTED")
    contract = invoke("contract.f", f'''
@import("jq")
print(jq.available())
print(jq.version())
print(jq.use_backend(1).error_code)
r := jq.run("{{\\"name\\":\\"Nift\\"}}", ".name", {{"raw":true,"compact":false,"extra_args":["--arg","value","$(touch {marker})"]}})
print(r.ok)
print(r.stdout.trim())
f := jq.file({json.dumps(input_path)}, ".name", {{"raw":true}})
print(f.ok)
print(f.stdout.trim())
print(jq.query("{{}}", ".", {{}}, {{}}).error_code)
print(jq.run("{{}}", ".", {{"unknown":true}}).error_code)
print(jq.use_backend("auto").error_code)
''')
    require(contract.returncode == 0, contract.stdout + contract.stderr)
    require(contract.stdout.strip().splitlines() == [
        "true", "jq-fixture-1.0", "invalid_backend", "true", "Nift",
        "true", "Nift", "invalid_options", "invalid_options", "backend_locked",
    ], contract.stdout + contract.stderr)
    require(not os.path.exists(marker), "shell metacharacters were executed")

    with open(log_path, encoding="utf-8") as handle:
        calls = [json.loads(line) for line in handle if line.strip()]
    require(len(calls) == 2, repr(calls))
    require(calls[0]["argv"][:-2] == [
        "--raw-output", "--arg", "value", "$(touch " + marker + ")", "--",
    ], repr(calls[0]))
    require(calls[0]["argv"][-2] == ".name", repr(calls[0]))
    require(os.path.basename(calls[0]["argv"][-1]).startswith(".nift-jq-"), repr(calls[0]))
    require(calls[1]["argv"] == ["--raw-output", "--", ".name", input_path], repr(calls[1]))
    require(not any(name.startswith(".nift-jq-") for name in os.listdir(temp_dir)), "temporary input leaked")

    disabled_source = r'''
@import("jq")
print(jq.available())
r := jq.run("{}", ".")
print(r.ok)
print(r.error_code)
print(r.exit_code)
'''
    expected_disabled = ["false", "false", "backend_unavailable", "127"]
    disabled = invoke("disabled.f", disabled_source, extra_args=("--no-process",))
    require(disabled.returncode == 0 and disabled.stdout.strip().splitlines() == expected_disabled, disabled.stdout + disabled.stderr)
    disabled_env = invoke("disabled-env.f", disabled_source, env={**base_env, "NIFT_NO_PROCESS": "1"})
    require(disabled_env.returncode == 0 and disabled_env.stdout.strip().splitlines() == expected_disabled, disabled_env.stdout + disabled_env.stderr)

    empty_bin = os.path.join(WORK, "empty-bin")
    os.makedirs(empty_bin)
    missing = invoke("missing.f", disabled_source, env={**base_env, "PATH": empty_bin})
    require(missing.returncode == 0 and missing.stdout.strip().splitlines() == expected_disabled, missing.stdout + missing.stderr)

    rooted = invoke("fs-root.f", r'''
@import("jq")
r := jq.run("{\"name\":\"rooted\"}", ".name", {"raw":true})
print(r.ok)
print(r.stdout.trim())
''', extra_args=("--fs-root=" + WORK,))
    require(rooted.returncode == 0 and rooted.stdout.strip().splitlines() == ["true", "rooted"], rooted.stdout + rooted.stderr)
    require(not any(name.startswith(".nift-jq-") for name in os.listdir(WORK)), "fs-root temporary input leaked")

    unavailable = invoke("no-secure-temp.f", r'''
@import("jq")
r := jq.run("{}", ".")
print(r.ok)
print(r.error_code)
print(r.exit_code == null)
print(jq.use_backend("auto").error_code)
''', env={**base_env, "PATH": fake_bin})
    require(unavailable.returncode == 0 and unavailable.stdout.strip().splitlines() == [
        "false", "temporary_file", "true", "backend_locked",
    ], unavailable.stdout + unavailable.stderr)
    print("PASS jq deterministic tests")
finally:
    shutil.rmtree(WORK, ignore_errors=True)
