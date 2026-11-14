"""Evaluate burst_merge on one raw burst from the microscope app (docs/units/burst-merge.md).

    python tools/fusion/burst_merge_eval.py <bursts>/<run_id>_cam<id> [--frames-a 0-7 --frames-b 8-15]
        [--unlit-ref <torch-off burst dir>] [--cli <burst_merge_cli>]

Runs the C merge (core/burst_merge, host CLI) on two disjoint, equal ranges of the burst, measures
the noise gain and its prediction with NumPy (merge_checks.py), and writes
results/<model>/burst_merge_<date>_<run_id>_cam<id>.json. The merged images stay in the burst
folder, outside the repository. Exit codes: 0 pass, 1 fail, 2 usage or input, 3 not judged
(the phone moved or stillness could not be shown, or the merge could not run).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_checks as mc  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CLI_CANDIDATES = ["build/core/burst_merge/burst_merge_cli", "build/core/burst_merge/Debug/burst_merge_cli.exe",
                  "build/core/burst_merge/Release/burst_merge_cli.exe"]


def parse_range(text: str) -> tuple[int, int]:
    lo, _, hi = text.partition("-")
    return int(lo), int(hi)


def find_cli(given: str | None) -> Path | None:
    for c in ([given] if given else CLI_CANDIDATES):
        p = Path(c) if Path(c).is_absolute() else REPO / c
        if p.exists():
            return p
    return None


def read_luma(path: Path, w: int, h: int):
    import numpy as np
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != w * h * 3 // 2:
        raise ValueError(f"{path}: {data.size} bytes, expected I420 {w}x{h}")
    return data[: w * h].reshape(h, w).astype(np.float64)


def read_pgm16(path: Path):
    import numpy as np
    raw = path.read_bytes()
    fields, pos = [], 0
    while len(fields) < 4:  # P5, width, height, maxval; exactly one whitespace byte follows maxval
        while raw[pos:pos + 1].isspace():
            pos += 1
        end = pos
        while not raw[end:end + 1].isspace():
            end += 1
        fields.append(raw[pos:end])
        pos = end
    if fields[0] != b"P5" or int(fields[3]) != 65535:
        raise ValueError(f"{path}: not a 16-bit binary PGM")
    w, h = int(fields[1]), int(fields[2])
    return np.frombuffer(raw[pos + 1: pos + 1 + 2 * w * h], dtype=">u2").reshape(h, w)


def run_merge(cli: Path, burst: Path, rng: tuple[int, int]) -> Path:
    out = burst / f"merge_{rng[0]:02d}-{rng[1]:02d}"
    subprocess.run([str(cli), str(burst), str(out), "--frames", f"{rng[0]}-{rng[1]}"], check=True,
                   capture_output=True, text=True, timeout=600)
    return out


def device_of(run_id: str, given: str | None) -> tuple[str, str | None]:
    if given:
        return given, None
    for p in sorted((REPO / "results").glob(f"*/microscope_live_*_{run_id}.json")):
        return p.parent.name, json.loads(p.read_text()).get("model")
    raise ValueError(f"no results/*/microscope_live_*_{run_id}.json; pass --device")


def measure(burst: Path, meta: dict, a, b, ya, yb) -> dict:
    w, h = meta["width"], meta["height"]
    first, last = min(a[0], b[0]), max(a[1], b[1])
    frames = [read_luma(burst / f"frame_{i:02d}.yuv", w, h) for i in range(first, last + 1)]
    idx_a = list(range(a[0] - first, a[1] - first + 1))
    idx_b = list(range(b[0] - first, b[1] - first + 1))
    n = len(idx_a)
    fa, fb = frames[idx_a[0]], frames[idx_b[0]]
    ma, mb = ya / 256.0, yb / 256.0
    c = mc.centre_half
    gamma = mc.variogram([c(f) for f in frames])
    integer = mc.motion(c(ma), c(mb))
    sub = mc.subpixel([c(f) for f in frames], idx_a, idx_b)
    return {"n": n, "gain": mc.gain(c(fa), c(fb), c(ma), c(mb)),
            "predicted_gain": mc.predicted_gain(gamma, idx_a, idx_b),
            "lag_correlation": mc.lag_correlation(gamma, n),
            "motion": {"integer": integer, "subpixel": sub, "moved": integer["moved"] or sub["moved"]},
            "exactness": mc.exactness([frames[i] for i in idx_a], ya), "luma_mean": float(c(fa).mean())}


def evaluate(args) -> int:
    burst = Path(args.burst)
    meta = json.loads((burst / "burst.json").read_text())
    n_frames = int(meta.get("frames", 0))
    a, b = mc.default_ranges(n_frames)
    a = parse_range(args.frames_a) if args.frames_a else a
    b = parse_range(args.frames_b) if args.frames_b else b
    mc.check_ranges(a, b, n_frames)
    run_id, camera = mc.run_and_camera(burst.name)
    slug, model = device_of(run_id, args.device)
    cli = find_cli(args.cli)
    if cli is None:
        raise ValueError("burst_merge_cli not built: cmake --build build/core")
    try:
        outs = [run_merge(cli, burst, r) for r in (a, b)]
    except subprocess.CalledProcessError as e:
        print(f"merge failed ({e.returncode}): {e.stderr.strip()}", file=sys.stderr)
        return 3
    m = measure(burst, meta, a, b, *(read_pgm16(o / "merged_y16.pgm") for o in outs))
    m["camera"] = camera
    report = {"unit": "burst_merge", "run_id": run_id, "model": model, "burst_dir": burst.name,
              "camera_id": camera, "width": meta["width"], "height": meta["height"],
              "frames_a": list(a), "frames_b": list(b), "torch": meta.get("torch"), **m}
    if args.unlit_ref:
        ref = Path(args.unlit_ref)
        ref_meta = json.loads((ref / "burst.json").read_text())
        off = mc.centre_half(read_luma(ref / "frame_00.yuv", ref_meta["width"], ref_meta["height"])).mean()
        exp_on = (meta.get("exposure_ns") or [None])[0]
        exp_off = (ref_meta.get("exposure_ns") or [None])[0]
        report["lighting"] = mc.lighting(m["luma_mean"], float(off), exp_on, exp_off)
    report.update(mc.verdict(m))
    out = REPO / "results" / slug / f"burst_merge_{dt.date.today():%Y%m%d}_{run_id}_cam{camera}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"verdict": report["verdict"], "gain": round(m["gain"], 3),
                      "predicted": round(m["predicted_gain"], 3), "file": str(out.relative_to(REPO))}))
    return {"pass": 0, "fail": 1}.get(report["verdict"], 3)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("burst")
    p.add_argument("--frames-a")
    p.add_argument("--frames-b")
    p.add_argument("--unlit-ref", help="torch-off burst of the same camera and scene")
    p.add_argument("--cli")
    p.add_argument("--device", help="results/<device> folder when no run report is found")
    args = p.parse_args(argv)
    try:
        return evaluate(args)
    except (ValueError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
