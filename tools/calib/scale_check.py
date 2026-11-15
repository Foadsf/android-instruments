#!/usr/bin/env python3
"""Check the microscope's µm per pixel against a ChArUco board (docs/units/microscope-scale.md).

    python tools/calib/scale_check.py BURSTS/<run>_scale --spec tools/calib/target_screen_lg_fhd_20px.json
        --calibration results/sm-n950f/camera_calibration_20261115_163037-f2e7.json
        [--model calibrated|no-breathing|nominal] [--square-mm 7.63875]

Each burst folder (bNN) holds raw I420 frames, burst.json (AF state per frame) and scale.json (the
app's µm per px per frame). Every frame's board scale comes from its corners, undistorted with the
calibration: the board's pose, and its depth on the centroid's ray over fx, which is the scale of
a plane square to the camera at that depth (what the thin-lens model predicts).

Exit codes: 0 pass; 1 fail; 2 usage error; 3 cannot judge (too few frames or distances).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

# Camera 0 calibration constants, as in Optics.kt (runs 155558-d0aa and 163037-f2e7, at 2.5 D).
CAM0_FX0, CAM0_D0, CAM0_SENSOR_MM, CAM0_WIDTH = 1136.5, 2.5, 5.645, 1440
FOCUSED = (2, 4)  # CONTROL_AF_STATE_PASSIVE_FOCUSED, FOCUSED_LOCKED
MIN_CORNERS = 12
FRAME_TOL, MEDIAN_TOL, PIPELINE_TOL = 0.02, 0.01, 0.001
MIN_FRAMES, MIN_DISTANCES, GAP_CM, NEAR_CM = 6, 3, 2.0, 12.0
MODELS = ("calibrated", "no-breathing", "nominal")


def camera0(width: int) -> tuple[float, float]:
    """(focal mm, pitch mm) of the thin lens through the calibration point: 1/f = 1/v0 + D0."""
    pitch = CAM0_SENSOR_MM / width
    v0 = CAM0_FX0 * width / CAM0_WIDTH * pitch
    return 1.0 / (1.0 / v0 + CAM0_D0 / 1000.0), pitch


def fx_px(lens: tuple[float, float], d: float | None) -> float | None:
    if d is None or not math.isfinite(d) or d <= 0:
        return None
    inv = 1.0 / lens[0] - d / 1000.0
    return None if inv <= 0 else 1.0 / inv / lens[1]


def um_per_px(lens: tuple[float, float], d: float | None) -> float | None:
    fx = fx_px(lens, d)
    return None if fx is None else 1e6 / (d * fx)


def predict(model: str, d: float | None, width: int) -> float | None:
    """µm per px at focus d for the model under test or a negative control."""
    if model == "calibrated":
        return um_per_px(camera0(width), d)
    if model == "nominal":
        return um_per_px((4.30, CAM0_SENSOR_MM / width), d)
    if model == "no-breathing":
        return None if d is None or not math.isfinite(d) or d <= 0 else 1e6 / (d * CAM0_FX0 * width / CAM0_WIDTH)
    raise ValueError(model)


def board_um_per_px(corners, ids, board, square_scale: float, k, dist) -> tuple[float, np.ndarray]:
    """(µm per px of a plane square to the camera through the board at the corners' centroid,
    centroid in undistorted pixels): the board's depth on the centroid's ray, from its pose
    (IPPE on undistorted corners), over fx. A wrong fx in k scales that depth and fx alike, so focus
    breathing does not bias it; a tilted board does not either."""
    import cv2
    import calib_core as cc
    obj = cc.object_points(board, ids, (square_scale, square_scale))
    und = cv2.undistortPoints(corners.reshape(-1, 1, 2).astype(np.float64), k, dist, P=k).reshape(-1, 2)
    ok, rvec, tvec = cv2.solvePnP(obj.astype(np.float64), und, k, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        raise ValueError("board pose not found")
    rot, _ = cv2.Rodrigues(rvec)
    c = und.mean(axis=0)
    ray = np.array([(c[0] - k[0, 2]) / k[0, 0], (c[1] - k[1, 2]) / k[1, 1], 1.0])
    n = rot[:, 2]
    z = float(n @ tvec.ravel()) / float(n @ ray)
    return z * 1000.0 / k[0, 0], c


def distances(cm: list[float]) -> int:
    s = sorted(cm)
    return 0 if not s else 1 + sum(1 for a, b in zip(s, s[1:]) if b - a >= GAP_CM)


def judge(frames: list[dict], model: str) -> dict:
    """frames: dicts with af_state, corners, focus_diopters, pred_um, board_um (None if not found)."""
    per = []
    for f in frames:
        d = f.get("focus_diopters")
        reason = ("focus not settled" if f.get("af_state") not in FOCUSED else
                  f"{f.get('corners', 0)} corners" if f.get("corners", 0) < MIN_CORNERS or f.get("board_um") is None else
                  "no scale" if f.get("pred_um") is None else
                  "not near" if model == "no-breathing" and 100.0 / d >= NEAR_CM else None)
        err = f["pred_um"] / f["board_um"] - 1 if reason is None else float("nan")
        per.append({**f, "judged": reason is None, "reason": reason or "", "err": err})
    judged = [r for r in per if r["judged"]]
    errs = [r["err"] for r in judged]
    n_dist = distances([100.0 / r["focus_diopters"] for r in judged])
    out = {"model": model, "frames": len(per), "frames_judged": len(judged), "distances": n_dist,
           "max_abs_err": max((abs(e) for e in errs), default=None),
           "median_err": float(np.median(errs)) if errs else None, "per_frame": per}
    enough = len(judged) >= MIN_FRAMES and (model != "calibrated" or n_dist >= MIN_DISTANCES)
    if not enough:
        out["verdict"] = "cannot judge"
    else:
        ok = out["max_abs_err"] <= FRAME_TOL and abs(out["median_err"]) <= MEDIAN_TOL
        out["verdict"] = "pass" if ok else "fail"
    return out


def load_frames(burst: Path, board, square_scale: float, k, dist, model: str) -> list[dict]:
    import calib_core as cc
    meta = json.loads((burst / "burst.json").read_text())
    scale = json.loads((burst / "scale.json").read_text())
    w, h = meta["width"], meta["height"]
    rows = []
    for i, f in enumerate(sorted(burst.glob("frame_*.yuv"))):
        img = np.fromfile(f, np.uint8)[: w * h].reshape(h, w)
        corners, ids = cc.detect_corners(img, board)
        n = 0 if ids is None else len(ids)
        um = board_um_per_px(corners, ids, board, square_scale, k, dist)[0] if n >= MIN_CORNERS else None
        d = meta["focus_distance_diopters"][i]
        app = scale["frames"][i]["um_per_px"]
        host = predict("calibrated", d, w)
        rows.append({"burst": burst.name, "frame": i, "af_state": meta["af_state"][i], "corners": n,
                     "focus_diopters": d, "board_um": um, "pred_um": predict(model, d, w), "app_um": app,
                     "pipeline_err": None if app is None or host is None else app / host - 1,
                     "gyro_max_rad_s": scale["frames"][i]["gyro_max_rad_s"], "exposure_ns": meta["exposure_ns"][i]})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="the run's <run>_scale folder with bNN bursts")
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--calibration", type=Path, required=True, help="camera_calibration_*.json (camera 0)")
    ap.add_argument("--model", choices=MODELS, default="calibrated")
    ap.add_argument("--square-mm", type=float, help="claimed square size (negative control); default: the spec's")
    ap.add_argument("--results", type=Path, default=REPO / "results" / "sm-n950f")
    args = ap.parse_args(argv)
    from make_target import board_object
    b = json.loads(args.spec.read_text())["board"]
    board = board_object(b)
    square_scale = (args.square_mm or b["square_mm"]) / b["square_mm"]
    c0 = json.loads(args.calibration.read_text())["cameras"]["0"]
    k = np.array([[c0["fx"], 0, c0["cx"]], [0, c0["fy"], c0["cy"]], [0, 0, 1.0]])
    bursts = sorted(p for p in args.folder.glob("b[0-9][0-9]") if p.is_dir())
    if not bursts:
        print(f"usage: no bNN bursts in {args.folder}", file=sys.stderr)
        return 2
    frames = [r for p in bursts for r in load_frames(p, board, square_scale, k, np.array(c0["dist"]), args.model)]
    res = judge(frames, args.model)
    pipe = [abs(r["pipeline_err"]) for r in frames if r["pipeline_err"] is not None]
    res["pipeline_max_err"] = max(pipe, default=None)
    if args.model == "calibrated" and (not pipe or res["pipeline_max_err"] > PIPELINE_TOL) and res["verdict"] == "pass":
        res["verdict"] = "fail"
    run_id = args.folder.name.removesuffix("_scale")
    tag = args.model if args.square_mm is None else f"{args.model}_square{args.square_mm}"
    res.update({"unit": "microscope_scale", "run_id": run_id, "spec": args.spec.name, "square_mm": args.square_mm or b["square_mm"],
                "calibration": args.calibration.name, "thresholds": {"frame": FRAME_TOL, "median": MEDIAN_TOL,
                "pipeline": PIPELINE_TOL, "min_frames": MIN_FRAMES, "min_distances": MIN_DISTANCES}})
    args.results.mkdir(parents=True, exist_ok=True)
    out = args.results / f"microscope_scale_check_{dt.date.today():%Y%m%d}_{run_id}_{tag}.json"
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps({k2: res[k2] for k2 in ("model", "square_mm", "frames", "frames_judged", "distances",
                                              "max_abs_err", "median_err", "pipeline_max_err", "verdict")}))
    print(f"wrote {out}")
    return {"pass": 0, "fail": 1}.get(res["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
