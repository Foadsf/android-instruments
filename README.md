# android-instruments

Turning Samsung Galaxy phones into measuring instruments (microscope, 3D scanner, compute device), one small verified unit at a time. GPL-3.0-or-later. No network permission.

This repository replaces seven earlier attempts (android-microscope, parallax, sfm-snr-mfsr, neural-enhance-bench, floss-android-microscope, android-multicam, android-hpc). They stay online, archived, as references; why and what is reused from each is in [docs/plan.md](docs/plan.md).

## The rule

A unit is done when its test passes in CI. A unit "works on the phone" only when a results file under [results/](results/) says so. Everything else is a claim.

## Layout

| Path | What |
|---|---|
| `core/` | C++17 units, host-testable, no Android or JNI. CMake + ctest. |
| `android/` | Thin Android apps (Kotlin, Camera2, UI). Pure logic lives in a `core` package with JVM tests. |
| `tools/` | Python: the lint gate, device tooling, fixture generators. |
| `results/` | Evidence from real phones, one folder per model. |
| `docs/units/` | One contract per unit: input, output, oracle, thresholds. |

## Status

| Stage | Unit | Host test | On a phone |
|---|---|---|---|
| 0 | `core/testing` harness with negative controls | green | n/a |
| 0 | `tools/lint` size and purity gate | green | n/a |
| 1 | `android/probe` device probe + `tools/probe` cross-check | green | [results/](results/README.md) |
| 1 | `android/halprobe` direct camera-HAL probe | n/a | Note8: telephoto found at HAL ID 3 |
| 1 | `core/camera_idmap` + `android/camshim` (expose uncounted vendor cameras) | green | shim verified unprivileged; install needs root |

## Build and test

```bash
python tools/lint/check_limits.py .
python -m unittest discover -s tools/lint -p "test_*.py"
python -m unittest discover -s tools/probe -p "test_*.py"
cmake -S core -B build/core && cmake --build build/core && ctest --test-dir build/core -C Debug
android/gradlew -p android assembleDebug testDebugUnitTest lintDebug
python tools/probe/run_probe.py
```
