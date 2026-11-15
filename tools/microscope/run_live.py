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
               ois: str = "default", series: int = 0, still_ms: int = 1000, focus: float | None = None,
               sweep: int = 0, gate: str = "0:0.04,2:0.02", max_exposure_us: int = 0, timing: int = 0,
               bridge_window: str | None = None) -> list[str]:
    """`am start` arguments. Pure: unit-testable. torch: off, on (the app picks the method),
    request (FLASH_MODE_TORCH in the open camera's request) or mode (CameraManager.setTorchMode).
    ois: default (the camera's) or off (LENS_OPTICAL_STABILIZATION_MODE_OFF requested).
    series > 0: the calibration capture series of that many still poses; sweep > 0: the hand-held
    sweep keeping that many gyro-calm frames per camera (camera-calibration.md)."""
    args = ["shell", "am", "start", "-W", "-n", ACTIVITY, "--es", "run_id", run_id,
            "--el", "stream_ms", str(stream_ms), "--ei", "burst", str(burst), "--es", "torch", torch,
            "--es", "ois", ois]
    if timing > 0:
        args += ["--ei", "timing", str(timing)]
    elif sweep > 0:
        args += ["--ei", "sweep", str(sweep), "--es", "gate_rad_s", gate]
        if bridge_window:
            args += ["--es", "bridge_window_ms", bridge_window]
    if (timing > 0 or sweep > 0) and max_exposure_us > 0:
        args += ["--el", "max_exposure_us", str(max_exposure_us)]
    elif series > 0:
        args += ["--ei", "series", str(series), "--el", "still_ms", str(still_ms)]
    if (series > 0 or sweep > 0) and focus is not None:
        args += ["--ef", "focus_diopters", str(focus)]
    return args + (["--es", "cameras", cameras] if cameras else [])


def parse_gates(text: str) -> dict[str, float]:
    """'0:0.04,2:0.02' -> {'0': 0.04, '2': 0.02}: the gyro limit per camera (camera-calibration.md,
    hand-held amendment). Raises ValueError on anything else."""
    out: dict[str, float] = {}
    for part in text.split(","):
        cam, sep, val = part.partition(":")
        rate = float(val) if sep and cam.strip() else float("nan")
        if not rate > 0 or cam.strip() in out:
            raise ValueError(f"gate {part!r}: want CAMERA:RAD_S with a positive rate, each camera once")
        out[cam.strip()] = rate
    return out


def bridge_window_from(result: dict) -> str | None:
    """'START,END' (ms from the stamp) for the sweep, from frame_timing.find_window on camera 2,
    or None if not trusted: could not tell, or a window not wholly before the stamp, which a stamp
    taken at delivery cannot have."""
    if not result.get("ok") or result["end_ms"] > 0:
        return None
    return f"{result['start_ms']},{result['end_ms']}"


def measure_bridge(adb: Adb, args: argparse.Namespace, out: Path) -> str | None:
    """Times camera 2 on the calibration scene (10 s of vibration pulses) and returns its window."""
    sys.path.insert(0, str(REPO / "tools" / "calib"))
    import frame_timing  # noqa: E402
    run_id = dt.datetime.now().strftime("%H%M%S") + "-" + secrets.token_hex(2)
    adb.run(*start_args(run_id, "2", args.stream_ms, args.burst, timing=10))
    t_args = argparse.Namespace(**{**vars(args), "timing": 10, "cameras": "2"})
    if run_timing(adb, t_args, run_id, out) != 0:
        return None
    ts_g, gyro, rep = frame_timing.load(args.bursts / f"{run_id}_timing")
    fr = rep["cameras"]["2"]["frames"]
    import numpy as np
    res = frame_timing.find_window(ts_g, gyro, np.array([f["ts_ns"] for f in fr], np.int64),
                                   np.array([f["sharpness"] for f in fr], float))
    (out / f"frame_timing_{dt.date.today():%Y%m%d}_{run_id}.json").write_text(json.dumps(res, indent=2) + "\n")
    window = bridge_window_from(res)
    print(f"camera 2 window: {res} -> {window or 'not trusted; the sweep keeps 150 ms before the stamp'}")
    adb.run("shell", "am", "force-stop", PACKAGE)
    return window


def run_timing(adb: Adb, args: argparse.Namespace, run_id: str, out: Path) -> int:
    """Waits for the frame-timing report, pulls it and the timing folder (camera-calibration.md)."""
    name = f"microscope_timing_{run_id}.json"
    print(f"timing {run_id}: point the phone at something with detail and hold it; it will buzz "
          f"for about {args.timing * len(args.cameras.split(','))} s")
    if not wait_for(adb, name, max(args.timeout, args.timing * 10)):
        print(f"could not tell: no report {name}", file=sys.stderr)
        return 3
    out.mkdir(parents=True, exist_ok=True)
    local = out / f"microscope_timing_{dt.date.today():%Y%m%d}_{run_id}.json"
    adb.run("pull", f"{REMOTE_DIR}/{name}", str(local))
    args.bursts.mkdir(parents=True, exist_ok=True)
    adb.run("pull", f"{REMOTE_DIR}/captures/{run_id}_timing", str(args.bursts), timeout=600)
    print(json.dumps({"report": str(local), "folder": str(args.bursts / f"{run_id}_timing")}, indent=2))
    print(f"next: python tools/calib/frame_timing.py {args.bursts / (run_id + '_timing')}")
    return 0


def run_series(adb: Adb, args: argparse.Namespace, run_id: str, out: Path) -> int:
    """Waits for the series report (minutes: Foad moves the phone), pulls it and the series folder."""
    name = f"microscope_series_{run_id}.json"
    timeout = max(args.timeout, args.series * 90, 400 if args.sweep else 0)
    if args.sweep:
        print(f"sweep {run_id}: point at the screen and move slowly around it; a short beep = a frame kept, "
              f"a long beep = next camera ({args.sweep} frames per camera)")
    else:
        print(f"series {run_id}: move the phone to a pose, hold it still until the beep, repeat ({args.series} poses)")
    if not wait_for(adb, name, timeout):
        print(f"could not tell: no report {name} after {timeout} s", file=sys.stderr)
        return 3
    out.mkdir(parents=True, exist_ok=True)
    local = out / f"microscope_series_{dt.date.today():%Y%m%d}_{run_id}.json"
    adb.run("pull", f"{REMOTE_DIR}/{name}", str(local))
    args.bursts.mkdir(parents=True, exist_ok=True)
    adb.run("pull", f"{REMOTE_DIR}/captures/{run_id}_series", str(args.bursts), timeout=1800)
    report = json.loads(local.read_text(encoding="utf-8"))
    ok = sum(1 for p in report.get("poses", []) if p.get("status") == "ok")
    print(json.dumps({"report": str(local), "series": str(args.bursts / f"{run_id}_series"), "end": report.get("end"),
                      "poses": len(report.get("poses", [])), "still_poses": ok}, indent=2))
    print(f"next: python tools/calib/calibrate.py {args.bursts / (run_id + '_series')} --board-mm W,H [--displacement A,B,100]")
    return 0


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
    # A calibration series always runs with OIS off (camera-calibration.md): the stabiliser moves
    # the image by ~1 px between frames of a still phone (burst-merge.md run 3).
    ois = "off" if args.series > 0 or args.sweep > 0 else args.ois
    window = args.bridge_window
    if args.sweep and args.measure_bridge and "2" in args.cameras.split(","):
        window = measure_bridge(adb, args, out)
    adb.run(*start_args(run_id, args.cameras, args.stream_ms, args.burst, args.torch, ois,
                        args.series, args.still_ms, args.focus, args.sweep, args.gate, args.max_exposure_us,
                        args.timing, window))
    if args.timing > 0:
        return run_timing(adb, args, run_id, out)
    if args.series > 0 or args.sweep > 0:
        return run_series(adb, args, run_id, out)
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
    ap.add_argument("--series", type=int, default=0, help="calibration series of N poses (OIS off unless --ois default)")
    ap.add_argument("--still-ms", type=int, default=1000, help="series: stillness needed before each pose")
    ap.add_argument("--focus", type=float, help="series/sweep: manual focus in diopters (camera 0)")
    ap.add_argument("--sweep", type=int, default=0, help="hand-held calibration: keep N gyro-calm frames per camera")
    ap.add_argument("--gate", default="0:0.04,2:0.02", help="sweep: gyro limit (rad/s) per camera over each kept frame")
    ap.add_argument("--max-exposure-us", type=int, default=0, help="sweep: cap camera 0's exposure (0: AE)")
    ap.add_argument("--timing", type=int, default=0, help="frame-timing run: SECONDS of vibration pulses per camera")
    ap.add_argument("--bridge-window", help="sweep: camera 2's exposure window START,END in ms from its stamp")
    ap.add_argument("--measure-bridge", action="store_true",
                    help="sweep: first time camera 2 on the scene (10 s of buzzing) and use its window")
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
    if args.series and not (1 <= args.series <= 40 and args.cameras):
        print("--series needs 1..40 poses and --cameras (e.g. 0,2)", file=sys.stderr)
        return 2
    if args.sweep and not (1 <= args.sweep <= 80 and args.cameras and not args.series):
        print("--sweep needs 1..80 frames, --cameras (e.g. 0,2), and no --series", file=sys.stderr)
        return 2
    if args.timing and not (3 <= args.timing <= 60 and args.cameras and not (args.series or args.sweep)):
        print("--timing needs 3..60 s, --cameras, and no --series or --sweep", file=sys.stderr)
        return 2
    try:
        missing = set(args.cameras.split(",")) - set(parse_gates(args.gate)) if args.sweep else set()
    except ValueError as e:
        print(f"--gate: {e}", file=sys.stderr)
        return 2
    if missing:
        print(f"--gate has no limit for camera(s) {sorted(missing)}", file=sys.stderr)
        return 2
    try:
        return run(Adb(args.serial, args.verbose, False), args)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
