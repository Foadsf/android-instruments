"""Checks a calibration-target PDF against its JSON spec, independently of the generator.

    python tools/calib/check_target.py tools/calib/target_a4_v1.pdf [--spec ...json] [--dpi 300]

Renders the PDF with PyMuPDF (not matplotlib, which drew it), finds the ChArUco board with
OpenCV's detector, and measures every inner corner in millimetres on the page against the
position the spec declares; probes the ruler, the texture's black fraction, the grey patches'
order and the slanted edge's angle. Exit 0 pass, 1 fail, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calib_core import detect_corners  # noqa: E402
from make_target import board_object  # noqa: E402  (the board definition, not the drawing)

MAX_CORNER_ERR_MM = 0.1
PAGE_TOL_PT = 0.5


def check(name: str, ok: bool, value, threshold) -> dict:
    return {"check": name, "ok": bool(ok), "value": value, "threshold": threshold}


def render(pdf: Path, dpi: int):
    import fitz
    import numpy as np
    doc = fitz.open(pdf)
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    return (page.rect.width, page.rect.height), len(doc), img


def board_checks(img, spec: dict, dpi: int) -> list[dict]:
    import numpy as np
    b = spec["board"]
    corners, ids = detect_corners(img, board_object(b))  # re-refined: the raw detector is +0.5 px off
    expected = (b["cols"] - 1) * (b["rows"] - 1)
    n = 0 if ids is None else len(ids)
    out = [check("ChArUco inner corners detected", n == expected, n, expected)]
    if n == 0:
        return out
    mm = corners * 25.4 / dpi
    # OpenCV's corner id i sits at column i % (cols-1), row i // (cols-1), one square in from the edge.
    ex = b["origin_mm"][0] + (ids % (b["cols"] - 1) + 1) * b["square_mm"]
    ey = b["origin_mm"][1] + (ids // (b["cols"] - 1) + 1) * b["square_mm"]
    # Pixel centres: a pixel's index i covers [i, i+1) * 25.4/dpi mm, so its centre is +0.5 px.
    err = np.hypot(mm[:, 0] + 12.7 / dpi - ex, mm[:, 1] + 12.7 / dpi - ey)
    out.append(check("corner position vs spec, max (mm)", err.max() <= MAX_CORNER_ERR_MM,
                     round(float(err.max()), 4), MAX_CORNER_ERR_MM))
    return out


def mm_to_px(v: float, dpi: int) -> int:
    return int(round(v * dpi / 25.4))


def probe_checks(img, spec: dict, dpi: int) -> list[dict]:
    out = []
    r = spec["ruler"]
    y = mm_to_px(r["start_mm"][1], dpi)
    xs = [mm_to_px(r["start_mm"][0] + f * r["length_mm"], dpi) for f in (0.0, 0.5, 1.0)]
    band = img[y - 2: y + 3]
    dark_ends = bool(all(band[:, x - 1: x + 2].min() < 100 for x in xs))
    beyond = bool(band[:, xs[-1] + mm_to_px(1.5, dpi)].min() > 200)
    out.append(check("ruler line spans exactly its length", dark_ends and beyond, [dark_ends, beyond], True))
    t = spec["texture"]
    x0, y0 = (mm_to_px(v, dpi) for v in t["origin_mm"])
    side = mm_to_px(t["side_mm"], dpi)
    frac = float((img[y0: y0 + side, x0: x0 + side] < 128).mean())
    out.append(check("texture black fraction", 0.4 <= frac <= 0.6, round(frac, 3), [0.4, 0.6]))
    g = spec["grey"]
    means = []
    for i in range(len(g["levels_black_fraction"])):
        gx = g["origin_mm"][0] + (i % g["cols"]) * (g["patch_mm"] + g["gap_mm"]) + g["patch_mm"] / 2
        gy = g["origin_mm"][1] + (i // g["cols"]) * (g["patch_mm"] + g["gap_mm"]) + g["patch_mm"] / 2
        h = mm_to_px(g["patch_mm"] / 4, dpi)
        means.append(float(img[mm_to_px(gy, dpi) - h: mm_to_px(gy, dpi) + h,
                               mm_to_px(gx, dpi) - h: mm_to_px(gx, dpi) + h].mean()))
    order = all(a > b for a, b in zip(means, means[1:]))
    out.append(check("grey patches darken in order", order, [round(m, 1) for m in means], "strictly decreasing"))
    out.append(check("slanted edge angle (deg)", *edge_angle_check(img, spec["slanted_edge"], dpi)))
    return out


def edge_angle_check(img, s: dict, dpi: int):
    """Angle of the square's top edge from the rows where it crosses mid-grey, by a line fit."""
    import numpy as np
    cx, cy = (mm_to_px(v, dpi) for v in s["centre_mm"])
    half = mm_to_px(s["side_mm"] / 2, dpi)
    xs, ys = [], []
    for x in range(cx - half // 2, cx + half // 2):
        col = img[cy - half - mm_to_px(4, dpi): cy, x].astype(float)
        idx = np.flatnonzero(col < 128)
        if idx.size:
            xs.append(x)
            ys.append(idx[0])
    slope = np.polyfit(xs, ys, 1)[0] if len(xs) > 10 else float("nan")
    ang = math.degrees(math.atan(slope))
    return abs(ang - s["angle_deg"]) <= 0.2, round(ang, 3), f"{s['angle_deg']} +- 0.2"


def evaluate(pdf: Path, spec: dict, dpi: int) -> dict:
    (w, h), pages, img = render(pdf, dpi)
    want = [round(v * 72 / 25.4, 3) for v in spec["page_mm"]]
    checks = [check("one page", pages == 1, pages, 1),
              check("page size matches the spec (pt)", abs(w - want[0]) <= PAGE_TOL_PT and abs(h - want[1]) <= PAGE_TOL_PT,
                    [round(w, 3), round(h, 3)], want)]
    checks += board_checks(img, spec, dpi) + probe_checks(img, spec, dpi)
    return {"verdict": "pass" if all(c["ok"] for c in checks) else "fail", "dpi": dpi, "checks": checks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--spec", type=Path)
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args(argv)
    spec_path = args.spec or args.pdf.with_suffix(".json")
    if not args.pdf.is_file() or not spec_path.is_file():
        print(f"missing {args.pdf} or {spec_path}", file=sys.stderr)
        return 2
    report = evaluate(args.pdf, json.loads(spec_path.read_text()), args.dpi)
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
