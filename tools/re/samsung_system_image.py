#!/usr/bin/env python3
"""Stream a Samsung firmware zip's system image to a raw ext4 file, without intermediate files.

    samsung_system_image.py <firmware.zip> <out.img> [--member system.img.lz4]

zip -> AP_*.tar.md5 -> system.img.lz4 (LZ4 frame) -> Android sparse image -> raw ext4.
Exit codes: 0 written, 1 member not found or bad image, 2 usage error.
"""
from __future__ import annotations

import argparse
import struct
import sys
import tarfile
import zipfile

import lz4.frame

SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW, CHUNK_FILL, CHUNK_DONT_CARE, CHUNK_CRC32 = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4


class SparseError(Exception):
    pass


def read_exact(stream, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        chunk = stream.read(n - len(out))
        if not chunk:
            raise SparseError(f"unexpected end of stream ({len(out)}/{n} bytes)")
        out += chunk
    return bytes(out)


def unsparse(src, dst) -> int:
    """Expands an Android sparse image from stream src into dst. Returns bytes written."""
    hdr = read_exact(src, 28)
    magic, major, _minor, file_hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, _crc = struct.unpack(
        "<IHHHHIIII", hdr)
    if magic != SPARSE_MAGIC or major != 1:
        raise SparseError(f"not a sparse image (magic 0x{magic:x}, major {major})")
    read_exact(src, file_hdr_sz - 28)
    written = 0
    for _ in range(total_chunks):
        ctype, _res, blocks, total_sz = struct.unpack("<HHII", read_exact(src, 12))
        read_exact(src, chunk_hdr_sz - 12)
        size = blocks * blk_sz
        if ctype == CHUNK_RAW:
            remaining = size
            while remaining:
                buf = read_exact(src, min(remaining, 1 << 20))
                dst.write(buf)
                remaining -= len(buf)
        elif ctype == CHUNK_FILL:
            pattern = read_exact(src, 4)
            block = pattern * (blk_sz // 4)
            for _b in range(blocks):
                dst.write(block)
        elif ctype == CHUNK_DONT_CARE:
            dst.seek(size, 1)
        elif ctype == CHUNK_CRC32:
            read_exact(src, total_sz - chunk_hdr_sz)
            continue
        else:
            raise SparseError(f"unknown chunk type 0x{ctype:x}")
        written += size
    if written != total_blks * blk_sz:
        raise SparseError(f"expanded {written} bytes, header says {total_blks * blk_sz}")
    # A trailing DONT_CARE chunk only seeks; truncate() does not extend every stream, so write
    # the last byte explicitly to give the image its full length.
    end = dst.seek(0, 2)
    if end < written:
        dst.seek(written - 1)
        dst.write(b"\0")
    dst.truncate(written)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("firmware")
    ap.add_argument("out")
    ap.add_argument("--member", default="system.img.lz4")
    args = ap.parse_args(argv)
    with zipfile.ZipFile(args.firmware) as z:
        names = [n for n in z.namelist() if n.startswith("AP_")]
        if not names:
            print("no AP_*.tar.md5 in the zip", file=sys.stderr)
            return 1
        with z.open(names[0]) as ap_stream, tarfile.open(fileobj=ap_stream, mode="r|") as tar:
            for m in tar:
                if m.name != args.member:
                    continue
                with lz4.frame.open(tar.extractfile(m)) as raw_src, open(args.out, "wb") as dst:
                    try:
                        n = unsparse(raw_src, dst)
                    except SparseError as e:
                        print(f"bad image: {e}", file=sys.stderr)
                        return 1
                print(f"wrote {args.out}: {n:,} bytes from {names[0]}/{args.member}")
                return 0
    print(f"{args.member} not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
