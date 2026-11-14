"""A4 calibration target for the phone cameras (docs/units/calib-target.md), as a vector PDF.

    python tools/calib/make_target.py [--out tools/calib/target_a4_v1.pdf]

Writes the PDF and a JSON spec beside it with every feature's position in millimetres on the page,
so the calibration code reads the geometry from the spec and never from a guess. Contents: a
ChArUco board (intrinsics, distortion, pose, scale), a slanted-edge square (MTF), a binary random
texture (alignment, NCC), grey patches (noise vs signal) and a 150 mm ruler (print-scale check).
Print at 100 % ("actual size"), never "fit to page".
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

PAGE_MM = (210.0, 297.0)
PX_PER_MM = 10  # board bitmap: 20 mm square = 200 px, 14 mm marker = 7 cells of 20 px
HERE = Path(__file__).resolve().parent


def default_spec() -> dict:
    return {
        "name": "android-instruments calibration target",
        "version": "a4-v1",
        "page_mm": list(PAGE_MM),
        "board": {"type": "charuco", "dictionary": "DICT_5X5_100", "cols": 9, "rows": 10,
                  "square_mm": 20.0, "marker_mm": 14.0, "origin_mm": [15.0, 22.0]},
        "slanted_edge": {"centre_mm": [40.0, 253.0], "side_mm": 30.0, "angle_deg": 5.0},
        "texture": {"origin_mm": [70.0, 228.0], "side_mm": 50.0, "px_per_mm": 5, "blur_mm": 1.0, "seed": 20261114},
        "grey": {"origin_mm": [128.0, 228.0], "patch_mm": 20.0, "gap_mm": 3.0, "cols": 3,
                 "levels_black_fraction": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]},
        "ruler": {"start_mm": [30.0, 287.0], "length_mm": 150.0},
    }


def board_object(b: dict):
    import cv2
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, b["dictionary"]))
    return cv2.aruco.CharucoBoard((b["cols"], b["rows"]), b["square_mm"], b["marker_mm"], d)


def board_bitmap(b: dict):
    """The board as a bitmap at PX_PER_MM, True = black. Sizes are chosen so every marker cell is a
    whole number of pixels: the drawing is exact, not resampled."""
    w = round(b["cols"] * b["square_mm"] * PX_PER_MM)
    h = round(b["rows"] * b["square_mm"] * PX_PER_MM)
    img = board_object(b).generateImage((w, h), marginSize=0, borderBits=1)
    return img < 128


def runs_to_rects(mask) -> list[tuple[int, int, int, int]]:
    """Black pixels of a boolean bitmap as rectangles (x, y, w, h) in pixels: runs per row, merged
    down while the next row has the same run."""
    import numpy as np
    open_rects: dict[tuple[int, int], list[int]] = {}
    out = []
    for y in range(mask.shape[0] + 1):
        runs = set()
        if y < mask.shape[0]:
            row = np.concatenate([[0], mask[y].astype(np.int8), [0]])
            edges = np.flatnonzero(np.diff(row))
            runs = {(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])}
        for key in list(open_rects):
            if key not in runs:
                y0 = open_rects.pop(key)[0]
                out.append((key[0], y0, key[1] - key[0], y - y0))
        for key in runs:
            open_rects.setdefault(key, [y])
    return out


def add_rects(ax, rects, scale_mm: float, origin_mm, grow: float = 0.01):
    """Draws bitmap rectangles in mm; grows each by `grow` mm so abutting fills leave no seam."""
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle
    ox, oy = origin_mm
    patches = [Rectangle((ox + x * scale_mm - grow, oy + y * scale_mm - grow), w * scale_mm + 2 * grow,
                         h * scale_mm + 2 * grow) for x, y, w, h in rects]
    ax.add_collection(PatchCollection(patches, facecolor="black", edgecolor="none", linewidth=0,
                                      antialiased=False))


def draw_slanted_edge(ax, s: dict):
    from matplotlib.patches import Polygon
    cx, cy = s["centre_mm"]
    half, a = s["side_mm"] / 2, math.radians(s["angle_deg"])
    pts = [(cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a))
           for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half))]
    ax.add_patch(Polygon(pts, closed=True, facecolor="black", edgecolor="none", linewidth=0))


def texture_bitmap(t: dict):
    """Binary random blobs: Gaussian-blurred white noise thresholded at its median (half black),
    from a fixed seed so the pattern can be regenerated exactly."""
    import numpy as np
    n = round(t["side_mm"] * t["px_per_mm"])
    rng = np.random.default_rng(t["seed"])
    noise = rng.normal(size=(n, n))
    sigma = t["blur_mm"] * t["px_per_mm"]
    k = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
    g = np.exp(-0.5 * (k / sigma) ** 2)
    g /= g.sum()
    sm = np.apply_along_axis(lambda r: np.convolve(np.pad(r, len(k), mode="wrap"), g, "same")[len(k):-len(k)], 1, noise)
    sm = np.apply_along_axis(lambda c: np.convolve(np.pad(c, len(k), mode="wrap"), g, "same")[len(k):-len(k)], 0, sm)
    return sm > np.median(sm)


def draw_greys(ax, g: dict):
    from matplotlib.patches import Rectangle
    for i, level in enumerate(g["levels_black_fraction"]):
        x = g["origin_mm"][0] + (i % g["cols"]) * (g["patch_mm"] + g["gap_mm"])
        y = g["origin_mm"][1] + (i // g["cols"]) * (g["patch_mm"] + g["gap_mm"])
        grey = 1.0 - level
        ax.add_patch(Rectangle((x, y), g["patch_mm"], g["patch_mm"], facecolor=(grey, grey, grey),
                               edgecolor="black", linewidth=0.3))
        ax.text(x + g["patch_mm"] / 2, y + g["patch_mm"] + 1.6, f"{round(level * 100)} %", ha="center",
                va="center", fontsize=5)


def draw_ruler(ax, r: dict):
    x0, y0 = r["start_mm"]
    lw = 0.15 * 72 / 25.4  # 0.15 mm in points
    ax.plot([x0, x0 + r["length_mm"]], [y0, y0], color="black", linewidth=lw, solid_capstyle="butt")
    for mm in range(int(r["length_mm"]) + 1):
        tick = 4.0 if mm % 10 == 0 else 2.5 if mm % 5 == 0 else 1.5
        ax.plot([x0 + mm, x0 + mm], [y0, y0 - tick], color="black", linewidth=lw, solid_capstyle="butt")
        if mm % 10 == 0:
            ax.text(x0 + mm, y0 - 5.2, str(mm), ha="center", va="bottom", fontsize=4.5)
    ax.text(x0 + r["length_mm"] / 2, y0 + 2.5, f"{r['length_mm']:.1f} mm from 0 to {int(r['length_mm'])}",
            ha="center", va="top", fontsize=5)


def draw_labels(ax, spec: dict):
    b = spec["board"]
    bw, bh = b["cols"] * b["square_mm"], b["rows"] * b["square_mm"]
    ax.text(15, 12, f"{spec['name']} {spec['version']}: print at 100 % (actual size), never fit to page.",
            fontsize=6.5, va="center")
    ax.text(15, 17, f"Check with a ruler: board {bw:.1f} x {bh:.1f} mm (outer edges of the squares), "
                    f"square {b['square_mm']:.1f} mm, ruler below {spec['ruler']['length_mm']:.1f} mm. "
                    f"ChArUco {b['cols']}x{b['rows']} {b['dictionary']}, marker {b['marker_mm']:.1f} mm.",
            fontsize=5, va="center")


def build(spec: dict, out_pdf: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pw, ph = spec["page_mm"]
    fig = plt.figure(figsize=(pw / 25.4, ph / 25.4))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, pw)
    ax.set_ylim(ph, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    b, t = spec["board"], spec["texture"]
    add_rects(ax, runs_to_rects(board_bitmap(b)), 1.0 / PX_PER_MM, b["origin_mm"])
    draw_slanted_edge(ax, spec["slanted_edge"])
    add_rects(ax, runs_to_rects(texture_bitmap(t)), 1.0 / t["px_per_mm"], t["origin_mm"])
    draw_greys(ax, spec["grey"])
    draw_ruler(ax, spec["ruler"])
    draw_labels(ax, spec)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, format="pdf")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=HERE / "target_a4_v1.pdf")
    args = ap.parse_args(argv)
    spec = default_spec()
    build(spec, args.out)
    args.out.with_suffix(".json").write_text(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"pdf": str(args.out), "spec": str(args.out.with_suffix(".json"))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
