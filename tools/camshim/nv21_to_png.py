#!/usr/bin/env python3
"""Convert a raw NV21 (yuv420sp) frame to PNG: nv21_to_png.py <in.yuv> <width> <height> <out.png>

Only the first width*height*3/2 bytes are used (a HAL1 callback may pass a larger heap).
Needs numpy and Pillow. Exit 0 written, 2 usage or size error.
"""
import sys

import numpy as np
from PIL import Image


def nv21_to_rgb(buf: bytes, w: int, h: int) -> np.ndarray:
    y = np.frombuffer(buf, np.uint8, w * h).reshape(h, w).astype(np.float32)
    vu = np.frombuffer(buf, np.uint8, w * h // 2, offset=w * h).reshape(h // 2, w // 2, 2).astype(np.float32)
    v = vu[:, :, 0].repeat(2, 0).repeat(2, 1) - 128.0
    u = vu[:, :, 1].repeat(2, 0).repeat(2, 1) - 128.0
    rgb = np.stack([y + 1.402 * v, y - 0.344 * u - 0.714 * v, y + 1.772 * u], axis=-1)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def main(argv):
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    path, w, h, out = argv[1], int(argv[2]), int(argv[3]), argv[4]
    data = open(path, "rb").read()
    if len(data) < w * h * 3 // 2:
        print(f"{path}: {len(data)} bytes < {w * h * 3 // 2} needed", file=sys.stderr)
        return 2
    rgb = nv21_to_rgb(data, w, h)
    Image.fromarray(rgb).save(out)
    print(f"wrote {out} ({w}x{h}); mean luma {np.frombuffer(data, np.uint8, w * h).mean():.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
