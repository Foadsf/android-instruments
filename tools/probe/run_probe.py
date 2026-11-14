#!/usr/bin/env python3
"""Run the device probe on a connected phone and file the evidence under results/<model>/.

Steps: install the APK, grant CAMERA, start the probe with a run id chosen here, wait for its
report, pull report and event log, capture `dumpsys media.camera`, run the Gate 1 cross-check.

Exit codes: 0 report pulled and cross-check passed; 1 cross-check found a mismatch;
3 could not tell (no phone, timeout, no report); 2 usage error.
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
import crosscheck  # noqa: E402

PACKAGE = "io.github.foadsf.instruments.probe"
ACTIVITY = f"{PACKAGE}/.MainActivity"
DEFAULT_APK = REPO / "android" / "probe" / "build" / "outputs" / "apk" / "debug" / "probe-debug.apk"
REMOTE_DIR = f"/sdcard/Android/data/{PACKAGE}/files"


class Adb:
    def __init__(self, serial: str | None, verbose: bool, dry_run: bool):
        self.base = ["adb"] + (["-s", serial] if serial else [])
        self.verbose, self.dry_run = verbose, dry_run

    def run(self, *args: str, check: bool = True, timeout: int = 120) -> str:
        cmd = self.base + list(args)
        if self.verbose or self.dry_run:
            print("+ " + " ".join(cmd), file=sys.stderr)
        if self.dry_run:
            return ""
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if check and p.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed ({p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout


def device_slug(adb: Adb) -> str:
    model = adb.run("shell", "getprop", "ro.product.model").strip() or "unknown"
    return model.lower().replace(" ", "-").replace("_", "-")


def start_probe(adb: Adb, apk: Path, run_id: str, verbose: bool, install: bool, trials: str | None) -> None:
    if install:
        adb.run("install", "-r", "-g", str(apk), timeout=300)
    adb.run("shell", "pm", "grant", PACKAGE, "android.permission.CAMERA", check=False)
    adb.run("shell", "am", "force-stop", PACKAGE)
    extra = ["--es", "trials", trials] if trials else []
    adb.run("shell", "am", "start", "-W", "-n", ACTIVITY, "--ez", "autorun", "true",
            "--es", "run_id", run_id, "--ez", "verbose", "true" if verbose else "false", *extra)


def wait_for_report(adb: Adb, run_id: str, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    name = f"probe_{run_id}.json"
    while time.monotonic() < deadline:
        listing = adb.run("shell", "ls", REMOTE_DIR, check=False)
        if name in listing.split():
            return True
        time.sleep(3)
    return False


def pull_evidence(adb: Adb, run_id: str, out_dir: Path, stamp: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "report": out_dir / f"probe_{stamp}_{run_id}.json",
        "events": out_dir / f"events_{stamp}_{run_id}.jsonl",
        "dumpsys": out_dir / f"dumpsys_media_camera_{stamp}_{run_id}.txt",
        "crosscheck": out_dir / f"crosscheck_{stamp}_{run_id}.json",
    }
    adb.run("pull", f"{REMOTE_DIR}/probe_{run_id}.json", str(files["report"]))
    adb.run("pull", f"{REMOTE_DIR}/events_{run_id}.jsonl", str(files["events"]), check=False)
    files["dumpsys"].write_text(adb.run("shell", "dumpsys", "media.camera"), encoding="utf-8")
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serial", help="adb serial (default: the only connected device)")
    ap.add_argument("--apk", type=Path, default=DEFAULT_APK)
    ap.add_argument("--no-install", action="store_true", help="use the APK already on the phone")
    ap.add_argument("--results", type=Path, default=REPO / "results")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for the report")
    ap.add_argument("--trials", help="only these trials: keys like 0+2 or kinds like CONTROL, comma-separated")
    ap.add_argument("-v", "--verbose", action="store_true", help="echo adb commands; DEBUG events on the phone")
    ap.add_argument("--dry-run", action="store_true", help="print the adb commands without running them")
    args = ap.parse_args(argv)
    if not args.no_install and not args.dry_run and not args.apk.is_file():
        print(f"APK not found: {args.apk} (build it: android/gradlew -p android assembleDebug)", file=sys.stderr)
        return 2
    adb = Adb(args.serial, args.verbose, args.dry_run)
    try:
        return run(adb, args)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3


def run(adb: Adb, args: argparse.Namespace) -> int:
    if not args.dry_run and "\tdevice" not in adb.run("devices"):
        print("could not tell: no phone in `adb devices`", file=sys.stderr)
        return 3
    run_id = dt.datetime.now().strftime("%H%M%S") + "-" + secrets.token_hex(2)
    stamp = dt.date.today().strftime("%Y%m%d")
    slug = "dry-run" if args.dry_run else device_slug(adb)
    start_probe(adb, args.apk, run_id, args.verbose, not args.no_install, args.trials)
    if args.dry_run:
        return 0
    if not wait_for_report(adb, run_id, args.timeout):
        print(f"could not tell: no report for run {run_id} after {args.timeout} s", file=sys.stderr)
        return 3
    files = pull_evidence(adb, run_id, args.results / slug, stamp)
    try:
        probe = json.loads(files["report"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"could not tell: report {files['report']} is not valid JSON ({e})", file=sys.stderr)
        return 3
    report = crosscheck.crosscheck(probe, files["dumpsys"].read_text(encoding="utf-8"))
    files["crosscheck"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: str(v) for k, v in files.items()}, indent=2))
    print(f"cross-check: {report['verdict']} ({report['matches']} match, {report['mismatches']} mismatch); "
          f"dual physical streams: {probe.get('dual_physical_streams')}")
    return {"pass": 0, "fail": 1}.get(report["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
