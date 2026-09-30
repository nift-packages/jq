# jq

Thin, safe Nift facade for the `jq` executable. The initial backend requires
`jq` on `PATH`; user-controlled data is always passed as structured argv and
never enters a shell or interpreter command string. The package does not
reimplement jq or decode jq output into Nift values.

## API

```text
@import("jq")

result := jq.run("{\"name\":\"Nift\"}", ".name", {"raw": true})
if(result.ok) { print(result.stdout) }

from_file := jq.file("data/input.json", ".items[]", {"compact": true})
```

The sole export is `jq`, with these methods:

- `available()`, `backends()`, `backend()`, `use_backend(name)`
- `capabilities()`, `version()`
- `run(input_json, expression, options?)`
- `query(input_json, expression, options?)`, an alias of `run`
- `file(input_path, expression, options?)`

`run`, `query`, and `file` return ordinary objects containing `ok`, `stdout`,
`stderr`, `exit_code`, `error`, `error_code`, and `backend`. jq output is
returned verbatim as text. Failures use `backend_unavailable`,
`invalid_options`, `temporary_file`, or `process_failed`.

Options are an object with boolean `raw`, `compact`, and `slurp` fields plus an
optional `extra_args` array of strings. Arguments are passed directly as an
argv vector. They are not interpreted by a shell. Unknown fields and values of
the wrong type return `invalid_options` without launching jq. `extra_args` is
advanced jq CLI access: its entries can intentionally change jq behavior, but
cannot become shell syntax. The facade inserts `--` before the filter and input
path so values beginning with `-` remain operands.

## Backend behavior

`auto` currently selects only `process`. `ffi` and `native` are reserved and
return `backend_unavailable`; unknown names return `unknown_backend`. The first
`run` or `file` attempt freezes backend selection. If `NIFT_NO_PROCESS` is set,
Nift is invoked with `--no-process`, or `jq` is absent from `PATH`, availability
checks and operations recover without attempting jq.

Nift cannot currently pass an in-memory string as process stdin, so `run`
writes its input to a temporary file. The package uses `mktemp` with an explicit
template under `NIFT_FS_ROOT` when set, otherwise under the configured temporary
root. On Windows, only when no filesystem root is configured, it may invoke a
fixed PowerShell temporary-file helper; no user-controlled data enters that
interpreter string. If neither secure creator is available, `run` fails closed
with `temporary_file`. Temporary inputs are removed on ordinary success and jq
error branches. Nift does not currently provide recoverable/finally-style
filesystem operations, so exceptional input write, save, or removal failures
may raise a Nift runtime error and leave the temporary source behind. Abrupt
process termination can likewise leave a file behind.

## Limitations

The package buffers jq stdout/stderr through Nift's process API. It does not
offer streaming, parse JSON results, validate filters itself, or hide jq exit
codes and diagnostics.

## Tests

Run the deterministic source/fake-executable suite and optional real-jq
integration with:

```sh
python3 tests/run.py /path/to/nift
```

The real integration reports `UNAVAILABLE` and exits successfully when jq is
not installed. It accepts the installed jq version rather than pinning one
specific release.
