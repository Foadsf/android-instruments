#!/usr/bin/env python3
"""Best scale of image B relative to reference A by normalised cross-correlation.

    ncc_scale.py ref img [--size WxH]

Shrinks the centre half of img by each trial scale s (img = ref magnified s times) and finds it in
ref with matchTemplate; prints the best s and its NCC. Works on blurred, low-texture frames where
ORB feature matching fails. Inputs are PNG/JPEG, or raw I420 (.yuv) with --size. Used to show that
camera 2 is the telephoto: telephoto vs wide is about 1.87 on the Note8 (docs/units/camera-bridge.md).

Exit codes: 0 printed a result; 2 usage error; 3 could not read an input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_gray(path: Path, size: tuple[int, int] | None, factor: float = 0.25):
    import cv2
    import numpy as np
    if path.suffix.lower() == ".yuv":
        if not size:
            raise ValueError(f"{path}: raw I420 needs --size WxH")
        w, h = size
        g = np.fromfile(path, dtype=np.uint8)[: w * h].reshape(h, w)
    else:
        g = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if g is None:
            raise ValueError(f"{path}: not an image")
    g = g.astype(np.float32)
    return cv2.resize(g, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA) if factor != 1 else g


def score(ref, img, s: float) -> float:
    import cv2
    h, w = img.shape
    crop = img[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    t = cv2.resize(crop, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA)
    if t.shape[0] >= ref.shape[0] or t.shape[1] >= ref.shape[1]:
        return -1.0
    return float(cv2.matchTemplate(ref, t, cv2.TM_CCOEFF_NORMED).max())


def best_scale(ref, img, lo: float = 0.80, hi: float = 2.30, step: float = 0.01) -> tuple[float, float]:
    n = int(round((hi - lo) / step)) + 1
    results = [(score(ref, img, round(lo + i * step, 2)), round(lo + i * step, 2)) for i in range(n)]
    ncc, s = max(results)
    return s, ncc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref", type=Path)
    ap.add_argument("img", type=Path)
    ap.add_argument("--size", help="WxH for raw I420 inputs")
    args = ap.parse_args(argv)
    size = None
    if args.size:
        try:
            w, h = (int(v) for v in args.size.lower().split("x"))
            size = (w, h)
        except ValueError:
            print(f"bad --size {args.size!r}, expected WxH", file=sys.stderr)
            return 2
    try:
        s, ncc = best_scale(load_gray(args.ref, size), load_gray(args.img, size))
    except (ValueError, OSError) as e:
        print(f"could not tell: {e}", file=sys.stderr)
        return 3
    print(json.dumps({"ref": str(args.ref), "img": str(args.img), "best_scale": s, "ncc": round(ncc, 3)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
