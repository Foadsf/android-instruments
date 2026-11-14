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
# Optional: the patched libexynoscamera3.so (tools/camshim/patch_exynoscamera3.py).
REMOTE_LIB = f"{REMOTE_DIR}/libexynoscamera3.so"
LIB_TARGET = "/system/lib/libexynoscamera3.so"


def _mount_steps(src: str, dst: str) -> list[list[str]]:
    return [
        ["shell", f"chmod 644 {src}"],
        ["shell", f"chcon {LABEL} {src}"],
        ["shell", f"mount -o bind {src} {dst}"],
    ]


def install_plan(with_lib: bool = False) -> list[list[str]]:
    """adb argument lists for install, after the files have been pushed. Pure: unit-tested."""
    steps = _mount_steps(REMOTE_SHIM, TARGET)
    if with_lib:
        steps += _mount_steps(REMOTE_LIB, LIB_TARGET)
    return steps + restart_plan()


def revert_plan() -> list[list[str]]:
    # -l: the running provider has the shim mapped, so a plain umount fails with EBUSY
    return [["shell", f"umount -l {TARGET}"], ["shell", f"umount -l {LIB_TARGET}"]] + restart_plan()


def restart_plan() -> list[list[str]]:
    return [["shell", f"setprop ctl.restart {s}"] for s in SERVICES]


def camera_count(dumpsys: str) -> int | None:
    m = re.search(r"Number of camera devices: (\d+)", dumpsys)
    return int(m.group(1)) if m else None


def shim_mounted(mounts: str, target: str = TARGET) -> bool:
    return any(line.split()[1:2] == [target] for line in mounts.splitlines() if line.strip())


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
    mounts = adb.run(["shell", "cat /proc/mounts"])
    mounted = shim_mounted(mounts)
    lib = shim_mounted(mounts, LIB_TARGET)
    count = camera_count(adb.run(["shell", "dumpsys media.camera"]))
    print(f"shim mounted: {mounted}; patched libexynoscamera3 mounted: {lib}; camera service devices: {count}")
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


def install(adb: Adb, shim: Path, lib: Path | None) -> int:
    for f in [shim] + ([lib] if lib else []):
        if not adb.dry_run and not f.is_file():
            print(f"missing: {f}", file=sys.stderr)
            return 2
    if not adb.dry_run and shim_mounted(adb.run(["shell", "cat /proc/mounts"])):
        print("already mounted; run revert first", file=sys.stderr)
        return 1
    adb.run(["shell", f"mkdir -p {REMOTE_DIR}"])
    adb.run(["push", str(shim), REMOTE_SHIM])
    if lib:
        adb.run(["push", str(lib), REMOTE_LIB])
    for step in install_plan(with_lib=lib is not None):
        adb.run(step)
    if adb.dry_run:
        return 0
    time.sleep(4)
    return status(adb)


def revert(adb: Adb) -> int:
    for step in revert_plan():
        adb.run(step, check=step[1].startswith("setprop"))  # an unmount of a path not mounted is fine
    if adb.dry_run:
        return 0
    time.sleep(4)
    return 0 if status(adb) == 1 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["status", "install", "revert"])
    ap.add_argument("--serial")
    ap.add_argument("--shim", type=Path, default=SHIM_BUILD)
    ap.add_argument("--patched-lib", type=Path,
                    help="also bind-mount this patched libexynoscamera3.so over /system/lib (install only)")
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
        return install(adb, args.shim, args.patched_lib) if args.action == "install" else revert(adb)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
