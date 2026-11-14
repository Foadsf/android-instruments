#!/usr/bin/env python3
"""Expose the Note8 telephoto to apps by bind-mounting the camera shim over the camera HAL.

    status   is the shim mounted, and how many cameras does the camera service see?
    install  push the shim, label it, bind-mount it over the 32-bit camera HAL, restart cameras
    revert   unmount and restart cameras (a reboot also reverts, unless persist was run)
    persist  survive reboots: one init script, /system/etc/init/instruments_camshim.rc, bind-mounts
             the shim at post-fs-data, before the camera provider starts
    unpersist  remove that init script (the current mount stays until revert or reboot)

All actions but status need adb running as root (Developer options -> Rooted debugging, then
`adb root`). install and revert write nothing to /system: the shim lives in /data/local/tmp and
is bind-mounted. persist writes only the init script (/ is plain ext4 on this build, no
dm-verity device); unpersist removes it.

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
# persist: one init script, the only file written under /system.
REMOTE_RC = f"{REMOTE_DIR}/instruments_camshim.rc"
RC_TARGET = "/system/etc/init/instruments_camshim.rc"
RC_LABEL = "u:object_r:system_file:s0"


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


def rc_text() -> str:
    """The init script persist installs. Pure: unit-tested."""
    return (
        "# android-instruments: bind-mount the camera shim over the camera HAL at every boot, before\n"
        "# the camera provider starts (class hal, on boot). Written by tools/camshim/note8_telephoto.py\n"
        "# persist; removed by unpersist. The shim itself stays in /data/local/tmp/instruments.\n"
        "on post-fs-data\n"
        f"    mount none {REMOTE_SHIM} {TARGET} bind\n"
    )


def persist_plan() -> list[list[str]]:
    """adb steps that install the init script (pushed to REMOTE_RC first). / is plain ext4 on the
    Note8 build (no dm-verity device), so a remount touches no verification. Pure: unit-tested."""
    return [
        ["shell", "mount -o remount,rw /"],
        ["shell", f"cp {REMOTE_RC} {RC_TARGET}"],
        ["shell", f"chmod 644 {RC_TARGET}"],
        ["shell", f"chcon {RC_LABEL} {RC_TARGET}"],
        ["shell", "mount -o remount,ro /"],
    ]


def unpersist_plan() -> list[list[str]]:
    return [["shell", "mount -o remount,rw /"], ["shell", f"rm -f {RC_TARGET}"], ["shell", "mount -o remount,ro /"]]


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
    rc = "post-fs-data" in adb.run(["shell", f"cat {RC_TARGET} 2>/dev/null"], check=False)
    print(f"shim mounted: {mounted}; patched libexynoscamera3 mounted: {lib}; camera service devices: {count}; "
          f"persists across reboot: {rc}")
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


def persist(adb: Adb, shim: Path) -> int:
    """Survive reboots: push the shim (if needed) and install the init script; reboot to verify."""
    if not adb.dry_run and not shim.is_file():
        print(f"missing: {shim}", file=sys.stderr)
        return 2
    adb.run(["shell", f"mkdir -p {REMOTE_DIR}"])
    mounted = not adb.dry_run and shim_mounted(adb.run(["shell", "cat /proc/mounts"]))
    if not mounted:  # pushing over a mounted shim would change the running provider's file
        adb.run(["push", str(shim), REMOTE_SHIM])
        for step in _mount_steps(REMOTE_SHIM, TARGET)[:2]:  # chmod + chcon, no mount
            adb.run(step)
    local_rc = Path(__file__).resolve().parent / "instruments_camshim.rc.tmp"
    local_rc.write_text(rc_text(), encoding="utf-8", newline="\n")
    try:
        adb.run(["push", str(local_rc), REMOTE_RC])
    finally:
        local_rc.unlink(missing_ok=True)
    for step in persist_plan():
        adb.run(step, check=step[1] != "mount -o remount,ro /")  # ro can be EBUSY; the rc is written
    if adb.dry_run:
        return 0
    ok = "post-fs-data" in adb.run(["shell", f"cat {RC_TARGET}"], check=False)
    print(f"init script {RC_TARGET}: {'installed' if ok else 'MISSING'}; takes effect at the next boot")
    return 0 if ok else 1


def unpersist(adb: Adb) -> int:
    for step in unpersist_plan():
        adb.run(step, check=step[1] != "mount -o remount,ro /")
    if adb.dry_run:
        return 0
    gone = adb.run(["shell", f"ls {RC_TARGET} 2>/dev/null"], check=False).strip() == ""
    print(f"init script removed: {gone}; the shim stays mounted until revert or reboot")
    return 0 if gone else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["status", "install", "revert", "persist", "unpersist"])
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
        if args.action == "persist":
            return persist(adb, args.shim)
        if args.action == "unpersist":
            return unpersist(adb)
        return install(adb, args.shim, args.patched_lib) if args.action == "install" else revert(adb)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
