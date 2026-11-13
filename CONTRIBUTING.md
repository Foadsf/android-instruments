# How work is done here

These rules exist because the seven earlier repositories were built feature-first and ended unmaintainable. Each rule answers a failure that actually happened (see docs/plan.md, section 1).

## Units

1. **One unit, one contract, one test, written before the code.** A unit is a folder. Its contract in `docs/units/<unit>.md` states input, output, oracle and pass thresholds. Thresholds are declared before the first run and changed only with a written reason.
2. **The oracle must not share code with what it checks.** A synthetic scene is rendered by code the reconstruction does not import; a port is checked against an independent reference (the Python implementation, an fp64 computation, OpenCV).
3. **Every test suite proves it can fail.** `core/` registers negative controls (`instruments_add_negative_control`) that must fail; ctest passes only when they do. A test binary with no cases fails.
4. **One unit per pull request.** A change that touches two units is split.

## Size and purity, enforced by `tools/lint/check_limits.py`

- A source file has at most 400 lines; a function at most 60.
- Anything under a `core` directory imports nothing from Android or JNI.

## Device evidence

- "Works on the phone" means a file in `results/<model>/` with the raw numbers, written by a tool (never typed by hand), plus the raw capture it came from when there is one.
- A device test declares its expected numbers before it is run.
- Device identifiers (adb serial, IMEI, hardware serial) are never committed.

## Logging (from the maintainability notes)

- Structured: one JSON object per line with `ts`, `level`, `run_id`, `event` and fields. No sentences with numbers interpolated into them.
- Verbosity is chosen at run time (`verbose` extra on Android, `-v` on CLIs). DEBUG lines are kept in a ring buffer and written before the next ERROR, so failures arrive with their trail.
- An error is logged once, at the boundary that handles it, with its context.

## CLIs

Every tool has `--help`, `-v/--verbose`, and where it touches a device `--dry-run`. Exit codes: 0 success, 1 a real negative (the check ran and failed), 2 usage error, 3 could not tell (the check could not run). A tool never reports 1 when it could not run.

## Working with AI agents

Give an agent one unit: its contract, its failing test, and the file it may port from. Never "build the app". The agent is done when CI is green and, for device units, when a results file exists; its own summary is not evidence.
