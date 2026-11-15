"""When does each camera expose, relative to its frame timestamp? (camera-calibration.md, frame
timing amendment)

    python tools/calib/frame_timing.py <bursts>/<run_id>_timing [--out FILE]

Input: the folder written by the microscope app's timing mode (run_live.py --timing): imu.csv
(raw gyroscope) and timing.json (per frame: timestamp, centre sharpness). The vibration motor
pulsed at random times; the gyroscope sees each pulse at once, and a frame whose exposure overlaps
one is blurred. For each camera this finds the window [ts + start, ts + end] whose high-passed gyro
energy best predicts the frames' loss of sharpness (Pearson r over a grid). Exit codes: 0 every
camera found, 1 a camera could not be told (r below MIN_R or too few pulses), 2 usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

MIN_R = 0.4          # below this the window is not trusted ("could not tell")
HP_MS = 40           # high-pass: subtract a 40 ms moving mean (removes hand tremor below ~15 Hz)
STARTS_MS = np.arange(-300, 101, 2)
WIDTHS_MS = np.arange(10, 151, 5)
MEDIAN_FRAMES = 31   # sharpness normalised by its running median (scene and focus drift)


CONTROL_TOL_MS = (6, 10)  # start, end: the synthetic tests' margins


def centre_window_ms(exposure_ms: float, skew_ms: float) -> tuple[float, float]:
    """The window of the centre-half rows, where sharpness is measured. The Camera2 stamp is the
    first row's exposure start, so row r of h is exposed over [r / h x skew, r / h x skew +
    exposure]; the centre half spans r / h from 1/4 to 3/4."""
    return (round(skew_ms / 4, 1), round(3 * skew_ms / 4 + exposure_ms, 1))


def vibration_energy(ts_ns: np.ndarray, gyro: np.ndarray) -> np.ndarray:
    """Squared norm of the gyro after removing its moving mean: vibration, not hand motion."""
    dt = np.median(np.diff(ts_ns)) / 1e6
    n = max(3, int(round(HP_MS / dt)) | 1)
    k = np.ones(n) / n
    low = np.column_stack([np.convolve(gyro[:, i], k, mode="same") for i in range(3)])
    return ((gyro - low) ** 2).sum(axis=1)


def blur_score(sharp: np.ndarray) -> np.ndarray:
    """1 - sharpness / running median: positive when a frame is softer than its neighbours."""
    h = MEDIAN_FRAMES // 2
    pad = np.pad(sharp, h, mode="edge")
    med = np.array([np.median(pad[i:i + MEDIAN_FRAMES]) for i in range(len(sharp))])
    return 1 - sharp / med


def find_window(ts_g: np.ndarray, gyro: np.ndarray, ts_f: np.ndarray, sharp: np.ndarray) -> dict:
    energy = vibration_energy(ts_g, gyro)
    cum = np.concatenate([[0.0], np.cumsum(energy)])
    y = blur_score(np.asarray(sharp, float))
    best = (-2.0, 0, 0)
    for w in WIDTHS_MS:
        for s in STARTS_MS:
            i0 = np.searchsorted(ts_g, ts_f + s * 1_000_000)
            i1 = np.searchsorted(ts_g, ts_f + (s + w) * 1_000_000)
            n = i1 - i0
            ok = n > 0
            if ok.sum() < 20:
                continue
            x = (cum[i1[ok]] - cum[i0[ok]]) / n[ok]
            r = float(np.corrcoef(x, y[ok])[0, 1]) if x.std() > 0 else 0.0
            if r > best[0]:
                best = (r, int(s), int(s + w))
    r, start, end = best
    return {"ok": r >= MIN_R, "r": round(r, 3), "start_ms": start, "end_ms": end, "min_r": MIN_R,
            "frames": int(len(ts_f))}


def load(root: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    rows = [line.split(",") for line in (root / "imu.csv").read_text().splitlines()[1:]]
    g = np.array([[float(v) for v in r[1:]] for r in rows if r[0] == "g"])
    order = np.argsort(g[:, 0])
    return g[order, 0].astype(np.int64), g[order, 1:], json.loads((root / "timing.json").read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if not (args.folder / "timing.json").is_file():
        print(f"no timing.json in {args.folder}", file=sys.stderr)
        return 2
    ts_g, gyro, rep = load(args.folder)
    out = {"unit": "frame_timing", "run_id": rep.get("run_id"), "cameras": {}}
    for cam, c in rep["cameras"].items():
        fr = c["frames"]
        res = find_window(ts_g, gyro, np.array([f["ts_ns"] for f in fr], np.int64),
                          np.array([f["sharpness"] for f in fr], float))
        exp = [f["exposure_ns"] for f in fr if f.get("exposure_ns")]
        skew = [f["skew_ns"] for f in fr if f.get("skew_ns")]
        if exp and skew:  # the control: the capture result gives the centre rows' window
            lo, hi = centre_window_ms(np.median(exp) / 1e6, np.median(skew) / 1e6)
            res["expected_centre_window_ms"] = [lo, hi]
            res["control_ok"] = bool(res["ok"] and abs(res["start_ms"] - lo) <= CONTROL_TOL_MS[0]
                                     and abs(res["end_ms"] - hi) <= CONTROL_TOL_MS[1])
        res["pulses_commanded"] = len(c.get("pulse_command_ns", []))
        out["cameras"][cam] = res
    text = json.dumps(out, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0 if all(r["ok"] and r.get("control_ok", True) for r in out["cameras"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
