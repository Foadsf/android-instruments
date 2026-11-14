#!/usr/bin/env python3
"""Expose the Note8 telephoto to apps by bind-mounting the camera shim over the camera HAL.

    status   is the shim mounted, and how many cameras does the camera service see?
    install  push the shim, label it, bind-mount it over the 32-bit camera HAL, restart cameras
    revert   unmount and restart cameras (a reboot also reverts: nothing on /system changes)

install and revert need adb running as root (Developer options -> Rooted debugging, then
`adb root`). Nothing is written to /system: the shim lives in /data/local/tmp and is
bind-mounted, so dm-verity and the system image stay untouched.

Exit codes: 0 done (status: shim active and >= 3 cameras); 1 checked and not active / verify
failed; 2 usage error; 3 could not tell (no phone, not root).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHIM_BUILD = REPO / "build" / "android-native" / "armeabi-v7a" / "camera.instruments_shim.so"
REMOTE_DIR = "/data/local/tmp/instruments"
REMOTE_SHIM = f"{REMOTE_DIR}/camera.universal8895.so"
TARGET = "/system/lib/hw/camera.universal8895.so"
LABEL = "u:object_r:system_lib_file:s0"
SERVICES = ["vendor.camera-provider-2-5", "cameraserver"]


def install_plan() -> list[list[str]]:
    """adb argument lists for install, after the shim has been pushed. Pure: unit-tested."""
    return [
        ["shell", f"chmod 644 {REMOTE_SHIM}"],
        ["shell", f"chcon {LABEL} {REMOTE_SHIM}"],
        ["shell", f"mount -o bind {REMOTE_SHIM} {TARGET}"],
    ] + restart_plan()


def revert_plan() -> list[list[str]]:
    return [["shell", f"umount {TARGET}"]] + restart_plan()


def restart_plan() -> list[list[str]]:
    return [["shell", f"setprop ctl.restart {s}"] for s in SERVICES]


def camera_count(dumpsys: str) -> int | None:
    m = re.search(r"Number of camera devices: (\d+)", dumpsys)
    return int(m.group(1)) if m else None


def shim_mounted(mounts: str) -> bool:
    return any(line.split()[1:2] == [TARGET] for line in mounts.splitlines() if line.strip())


class Adb:
    def __init__(self, serial: str | None, verbose: bool, dry_run: bool):
        self.base = ["adb"] + (["-s", serial] if serial else [])
        self.verbose, self.dry_run = verbose, dry_run

    def run(self, args: list[str], check: bool = True) -> str:
        cmd = self.base + args
        if self.verbose or self.dry_run:
            print("+ " + " ".join(cmd), file=sys.stderr)
        if self.dry_run:
            return ""
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if check and p.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)}: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout


def status(adb: Adb) -> int:
    mounted = shim_mounted(adb.run(["shell", "cat /proc/mounts"]))
    count = camera_count(adb.run(["shell", "dumpsys media.camera"]))
    print(f"shim mounted: {mounted}; camera service devices: {count}")
    return 0 if mounted and (count or 0) >= 3 else 1


def require_root(adb: Adb) -> bool:
    if adb.dry_run:
        return True
    if "uid=0" in adb.run(["shell", "id"]):
        return True
    adb.run(["root"], check=False)
    time.sleep(3)
    adb.run(["wait-for-device"], check=False)
    return "uid=0" in adb.run(["shell", "id"], check=False)


def install(adb: Adb, shim: Path) -> int:
    if not adb.dry_run and not shim.is_file():
        print(f"shim not built: {shim} (pwsh android/camshim/build.ps1)", file=sys.stderr)
        return 2
    if not adb.dry_run and shim_mounted(adb.run(["shell", "cat /proc/mounts"])):
        print("already mounted; run revert first", file=sys.stderr)
        return 1
    adb.run(["shell", f"mkdir -p {REMOTE_DIR}"])
    adb.run(["push", str(shim), REMOTE_SHIM])
    for step in install_plan():
        adb.run(step)
    if adb.dry_run:
        return 0
    time.sleep(4)
    return status(adb)


def revert(adb: Adb) -> int:
    for step in revert_plan():
        adb.run(step, check=step[1].startswith("setprop"))
    if adb.dry_run:
        return 0
    time.sleep(4)
    return 0 if status(adb) == 1 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["status", "install", "revert"])
    ap.add_argument("--serial")
    ap.add_argument("--shim", type=Path, default=SHIM_BUILD)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the adb commands without running them")
    args = ap.parse_args(argv)
    adb = Adb(args.serial, args.verbose, args.dry_run)
    try:
        if args.action == "status":
            return status(adb)
        if not require_root(adb):
            print("could not tell: adb is not root. Enable Developer options -> Rooted debugging, then retry.",
                  file=sys.stderr)
            return 3
        return install(adb, args.shim) if args.action == "install" else revert(adb)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
