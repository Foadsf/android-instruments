#!/usr/bin/env python3
"""Patch the Note8 (LineageOS 20) 32-bit libexynoscamera3.so: 5 raw (FLITE) buffers per camera.

Why: with the telephoto exposed, opening wide + telephoto fails because each camera takes 7
raw buffers of 24.4 MB from a reserved pool that holds about 15 (docs/re/note8-telephoto-dual-mode.md).
With 5, two cameras need 5 + 2 + 5 + 2 = 14.

Patches (Thumb-2, file offset = vaddr - 0x4000):
  0x8e192  movs r0, #7 -> #5   ExynosCamera3::m_setConfigInform: config bufInfo field +0x388
  0x9e52c  movs r1, #7 -> #5   ExynosCamera3::m_setBuffers: setContigBufCount(7) for FLITE

The tool refuses unless the input is exactly the analysed build (SHA-256) and the original bytes
are present. Exit codes: 0 written, 1 refused (wrong input), 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SOURCE_SHA256 = "6ad55bc28f0d59ac6598885d49472e344f1bc2dea6c5a80c4cea0d2d62f434f1"
PATCHES = [
    # (file offset, original bytes, patched bytes, what)
    (0x8E192, bytes.fromhex("0720"), bytes.fromhex("0520"), "movs r0,#7 -> #5 (config raw buffer count)"),
    (0x9E52C, bytes.fromhex("0721"), bytes.fromhex("0521"), "movs r1,#7 -> #5 (reserved FLITE buffers)"),
]


class Refused(Exception):
    pass


def patch(data: bytes, expected_sha256: str = SOURCE_SHA256) -> bytes:
    """Returns the patched image; raises Refused if the input is not the expected build."""
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise Refused(f"input SHA-256 {actual} is not the analysed build {expected_sha256}")
    out = bytearray(data)
    for off, old, new, what in PATCHES:
        if out[off:off + len(old)] != old:
            raise Refused(f"0x{off:x}: expected {old.hex()} for '{what}', found {out[off:off + len(old)].hex()}")
        out[off:off + len(new)] = new
    return bytes(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="libexynoscamera3.so pulled from /system/lib")
    ap.add_argument("output", type=Path)
    args = ap.parse_args(argv)
    if not args.source.is_file():
        print(f"not a file: {args.source}", file=sys.stderr)
        return 2
    try:
        patched = patch(args.source.read_bytes())
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    args.output.write_bytes(patched)
    print(f"wrote {args.output} sha256={hashlib.sha256(patched).hexdigest()}")
    for off, old, new, what in PATCHES:
        print(f"  0x{off:x}: {old.hex()} -> {new.hex()}  {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
