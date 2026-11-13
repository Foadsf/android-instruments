# Instructions for coding agents

Read [CONTRIBUTING.md](CONTRIBUTING.md) first; its rules bind you. In short:

- Work on one unit at a time, against its contract in `docs/units/`. If the contract does not exist, write it (input, output, oracle, thresholds) and stop for review before writing code.
- Write the test first and see it fail. Keep the negative controls failing.
- Run before claiming done: `python tools/lint/check_limits.py .`, the Python tool tests, the core ctest, and `android/gradlew -p android testDebugUnitTest lintDebug`.
- Never write a number into `results/` by hand and never claim device behaviour without a results file.
- Do not port code from the archived repositories wholesale. Port one function at a time, with the test that proves it.
- Keep files under 400 lines and functions under 60; keep `core` free of Android and JNI.
