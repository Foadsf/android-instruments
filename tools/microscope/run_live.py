#!/usr/bin/env python3
"""Run the microscope-live evidence run on a connected phone and file the result.

Installs the APK, grants CAMERA, starts the app with a run id chosen here, waits for its report,
pulls it to results/<model>/, pulls the raw bursts to --bursts (outside the repo: images are not
committed), checks the report against the contract's thresholds, and recomputes the sharpness
score from the raw frames with NumPy.

Exit codes: 0 all checks pass; 1 a check failed; 2 usage error; 3 could not tell (no phone,
timeout, no report).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "probe"))
import live_checks  # noqa: E402
from run_probe import Adb, device_slug  # noqa: E402

PACKAGE = "io.github.foadsf.instruments.microscope"
ACTIVITY = f"{PACKAGE}/.MainActivity"
DEFAULT_APK = REPO / "android" / "microscope" / "build" / "outputs" / "apk" / "debug" / "microscope-debug.apk"
REMOTE_DIR = f"/sdcard/Android/data/{PACKAGE}/files"
DEFAULT_BURSTS = REPO.parent / "note8_camera_stack" / "bursts"


TORCH_MODES = ("off", "on", "request", "mode")


def start_args(run_id: str, cameras: str | None, stream_ms: int, burst: int, torch: str = "off",
               ois: str = "default") -> list[str]:
    """`am start` arguments. Pure: unit-testable. torch: off, on (the app picks the method),
    request (FLASH_MODE_TORCH in the open camera's request) or mode (CameraManager.setTorchMode).
    ois: default (the camera's) or off (LENS_OPTICAL_STABILIZATION_MODE_OFF requested)."""
    args = ["shell", "am", "start", "-W", "-n", ACTIVITY, "--es", "run_id", run_id,
            "--el", "stream_ms", str(stream_ms), "--ei", "burst", str(burst), "--es", "torch", torch,
            "--es", "ois", ois]
    return args + (["--es", "cameras", cameras] if cameras else [])


def wait_for(adb: Adb, name: str, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if name in adb.run("shell", "ls", REMOTE_DIR, check=False).split():
            return True
        time.sleep(2)
    return False


def pull(adb: Adb, run_id: str, report: dict, out: Path, bursts: Path) -> list[dict]:
    """Pulls each camera's burst folder and runs the sharpness cross-check on it."""
    extra = []
    for cam in report.get("cameras", []):
        b = cam.get("burst")
        if not b:
            continue
        bursts.mkdir(parents=True, exist_ok=True)
        adb.run("pull", f"{REMOTE_DIR}/captures/{b['dir']}", str(bursts), timeout=600)
        try:
            extra.append({"camera_id": cam["camera_id"], **live_checks.sharpness_crosscheck(bursts / b["dir"], b)})
        except (ValueError, OSError, ImportError) as e:
            extra.append({"camera_id": cam["camera_id"], **live_checks.check("sharpness cross-check", False, str(e), "")})
    return extra


def run(adb: Adb, args: argparse.Namespace) -> int:
    if "\tdevice" not in adb.run("devices"):
        print("could not tell: no phone in `adb devices`", file=sys.stderr)
        return 3
    run_id = dt.datetime.now().strftime("%H%M%S") + "-" + secrets.token_hex(2)
    stamp = dt.date.today().strftime("%Y%m%d")
    out = args.results / device_slug(adb)
    if not args.no_install:
        adb.run("install", "-r", "-g", str(args.apk), timeout=300)
    adb.run("shell", "pm", "grant", PACKAGE, "android.permission.CAMERA", check=False)
    adb.run("shell", "am", "force-stop", PACKAGE)
    adb.run(*start_args(run_id, args.cameras, args.stream_ms, args.burst, args.torch, args.ois))
    name = f"microscope_live_{run_id}.json"
    if not wait_for(adb, name, args.timeout):
        print(f"could not tell: no report {name} after {args.timeout} s", file=sys.stderr)
        return 3
    out.mkdir(parents=True, exist_ok=True)
    local = out / f"microscope_live_{stamp}_{run_id}.json"
    adb.run("pull", f"{REMOTE_DIR}/{name}", str(local))
    report = json.loads(local.read_text(encoding="utf-8"))
    result = live_checks.verdict(report)
    result["sharpness"] = pull(adb, run_id, report, out, args.bursts)
    if not all(c["ok"] for c in result["sharpness"]):
        result["verdict"] = "fail"
    checks = out / f"microscope_live_checks_{stamp}_{run_id}.json"
    checks.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(local), "checks": str(checks), "bursts": str(args.bursts)}, indent=2))
    for cam, items in result["cameras"].items():
        print(f"camera {cam}: " + "; ".join(f"{c['check']} {c['value']} {'ok' if c['ok'] else 'FAIL'}" for c in items))
    print(f"verdict: {result['verdict']}")
    return 0 if result["verdict"] == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serial")
    ap.add_argument("--apk", type=Path, default=DEFAULT_APK)
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--cameras", help="comma-separated camera ids, in order (default: the app's choice, camera 2)")
    ap.add_argument("--stream-ms", type=int, default=10_000)
    ap.add_argument("--burst", type=int, default=16)
    ap.add_argument("--torch", choices=TORCH_MODES, default="off", help="flash LED during the run")
    ap.add_argument("--ois", choices=("default", "off"), default="default", help="optical stabilisation")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--results", type=Path, default=REPO / "results")
    ap.add_argument("--bursts", type=Path, default=DEFAULT_BURSTS, help="where raw bursts go (keep outside the repo)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not args.no_install and not args.apk.is_file():
        print(f"APK not found: {args.apk} (build: android/gradlew -p android :microscope:assembleDebug)", file=sys.stderr)
        return 2
    if not 1 <= args.burst <= 32 or not 500 <= args.stream_ms <= 60_000:
        print("--burst must be 1..32 and --stream-ms 500..60000", file=sys.stderr)
        return 2
    try:
        return run(Adb(args.serial, args.verbose, False), args)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
