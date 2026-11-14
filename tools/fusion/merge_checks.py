"""Measurements and verdict for burst_merge (docs/units/burst-merge.md), host side, NumPy.

Written independently of the C merge: the gain is measured from two disjoint halves of one burst
(the static scene cancels in their difference), and predicted from the single frames' residual
autocorrelation. The thresholds are the ones the contract declared before the first run.
"""
from __future__ import annotations

import re

PRED_REL_TOL = 0.10
USEFUL_FRACTION = 0.9
USEFUL_CAMERA = "0"
MIN_PEAK = 0.1
MAX_MOTION_SHARE = 0.05  # motion adding 5 % to var(A - B) biases the gain by about 2.5 %
LIT_RATIO = 1.5


def check(name: str, ok: bool, value, threshold) -> dict:
    return {"check": name, "ok": bool(ok), "value": value, "threshold": threshold}


def centre_half(a):
    h, w = a.shape[-2:]
    return a[..., h // 4: h // 4 + h // 2, w // 4: w // 4 + w // 2]


def diff_std(a, b) -> float:
    import numpy as np
    d = np.asarray(a, np.float64) - np.asarray(b, np.float64)
    return float((d - d.mean()).std(ddof=1))


def gain(fa, fb, merged_a, merged_b) -> float:
    """Single-frame difference over merged-half difference, each with its mean removed (so a
    global exposure offset between the halves does not count as noise)."""
    m = diff_std(merged_a, merged_b)
    return diff_std(fa, fb) / m if m > 0 else float("inf")


def variogram(frames) -> list[float]:
    """gamma(k) = 0.5 * var(f[i+k] - f[i]) for k = 0..M-1, averaged over all frame pairs at lag k,
    each difference with its own mean removed. The static scene cancels in every difference and no
    temporal mean is subtracted, so correlated noise is not biased (a mean-subtracted
    autocorrelation is: 15 % off on AR(1) noise with rho 0.4 over 32 frames)."""
    import numpy as np
    s = np.asarray(frames, np.float64)
    out = [0.0]
    for k in range(1, s.shape[0]):
        d = s[k:] - s[:-k]
        d = d - d.mean(axis=(1, 2), keepdims=True)
        out.append(0.5 * float((d * d).mean()))
    return out


def predicted_gain(gamma: list[float], idx_a: list[int], idx_b: list[int]) -> float:
    """Gain the variogram predicts for the halves' means: var(f_a - f_b) / var(mean A - mean B).
    For zero-sum weights w, var(sum w_i f_i) = -sum_{i<j} w_i w_j 2 gamma(|i-j|); so the
    prediction needs no noise level, no reference and no temporal mean."""
    n = len(idx_a)
    w = {i: 1.0 / n for i in idx_a}
    w.update({i: -1.0 / n for i in idx_b})
    items = sorted(w.items())
    var_ab = -sum(wi * wj * 2 * gamma[abs(j - i)]
                  for x, (i, wi) in enumerate(items) for j, wj in items[x + 1:])
    single = 2 * gamma[abs(idx_b[0] - idx_a[0])]
    return (single / var_ab) ** 0.5 if var_ab > 0 else float("inf")


def lag_correlation(gamma: list[float], ref_lag: int) -> list[float]:
    """rho(k) relative to lag ref_lag (1 - gamma(k) / gamma(ref)), for the report only."""
    ref = gamma[ref_lag]
    return [round(1 - g / ref, 4) for g in gamma[1:ref_lag]] if ref > 0 else []


def motion(a, b) -> dict:
    """Integer shift between two images by phase correlation, and the correlation peak. A run is
    'moved' when the shift is not (0, 0) or the peak is too weak to show stillness at all."""
    import numpy as np
    fa = np.fft.fft2(a - a.mean())
    fb = np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    c = np.fft.ifft2(r / (np.abs(r) + 1e-12)).real
    y, x = np.unravel_index(int(np.argmax(c)), c.shape)
    h, w = c.shape
    shift = [int(y if y <= h // 2 else y - h), int(x if x <= w // 2 else x - w)]
    peak = float(c.max())
    return {"shift": shift, "peak": round(peak, 4), "moved": shift != [0, 0] or peak < MIN_PEAK,
            "threshold": {"shift": [0, 0], "min_peak": MIN_PEAK}}


def subpixel(frames, idx_a=None, idx_b=None) -> dict:
    """Global sub-pixel shift of every frame against the burst mean (one Lucas-Kanade step on the
    mean's gradient, with an offset term), and the share of var(mean A - mean B) that the shift
    between the halves explains: var((s_A - s_B) . grad) / var(A - B). The gain is measured on
    that difference, so this is the scale on which motion matters; the integer phase-correlation
    check misses a smooth drift whose half-means differ by under half a pixel. Moved above
    MAX_MOTION_SHARE. Default halves: first and second half of the frames."""
    import numpy as np
    s = np.asarray(frames, np.float64)
    half = len(s) // 2
    idx_a = list(range(half)) if idx_a is None else idx_a
    idx_b = list(range(half, 2 * half)) if idx_b is None else idx_b
    m = s.mean(axis=0)
    gy, gx = np.gradient(m)
    g = np.stack([gx.ravel(), gy.ravel(), np.ones(m.size)], 1)
    sh = np.array([np.linalg.lstsq(g, (f - m).ravel(), rcond=None)[0][:2] for f in s]) * -1
    d = sh[idx_a].mean(axis=0) - sh[idx_b].mean(axis=0)
    motion_field = -(d[0] * gx + d[1] * gy)
    diff = s[idx_a].mean(axis=0) - s[idx_b].mean(axis=0)
    share = float(motion_field.var() / diff.var()) if diff.var() > 0 else 0.0
    return {"shift_ptp_px": [round(float(np.ptp(sh[:, 0])), 3), round(float(np.ptp(sh[:, 1])), 3)],
            "half_shift_px": [round(float(d[0]), 4), round(float(d[1]), 4)],
            "motion_share": round(share, 4), "moved": share > MAX_MOTION_SHARE, "threshold": MAX_MOTION_SHARE}


def lighting(mean_on: float, mean_off: float, exp_on: int | None = None, exp_off: int | None = None) -> dict:
    """Whether the torch burst was lit by the torch. Auto-exposure brings a lit picture back to its
    target, so in a lit room the luma barely rises; where the camera reports exposure, a drop of
    the same ratio shows the light. Without either, it is 'not shown' (not proof it stayed dark)."""
    ratio = mean_on / mean_off if mean_off > 0 else float("inf")
    exp_ratio = exp_off / exp_on if exp_on and exp_off else None
    lit = ratio >= LIT_RATIO or (exp_ratio is not None and exp_ratio >= LIT_RATIO)
    return {"luma_on": round(mean_on, 3), "luma_off": round(mean_off, 3), "luma_ratio": round(ratio, 3),
            "exposure_ratio_off_over_on": round(exp_ratio, 3) if exp_ratio else None,
            "status": "lit" if lit else "not shown", "threshold": LIT_RATIO}


def exactness(frames, y16) -> dict:
    """The C merge's Q8.8 luma against a double mean computed here: exact rounding allows
    |error| <= 0.5/256 (plus float slack)."""
    import numpy as np
    mean = np.asarray(frames, np.float64).mean(axis=0)
    err = float(np.abs(np.asarray(y16, np.float64) / 256.0 - mean).max())
    return {"ok": err <= 0.5 / 256 + 1e-9, "max_abs_error": err, "threshold": 0.5 / 256}


def default_ranges(n_frames: int) -> tuple[tuple[int, int], tuple[int, int]]:
    half = n_frames // 2
    return (0, half - 1), (half, 2 * half - 1)


def check_ranges(a: tuple[int, int], b: tuple[int, int], n_frames: int) -> None:
    for lo, hi in (a, b):
        if lo < 0 or hi < lo or hi >= n_frames:
            raise ValueError(f"range {lo}-{hi} outside the burst of {n_frames} frames")
    if a[1] - a[0] != b[1] - b[0]:
        raise ValueError("ranges A and B must have the same length")
    if not (a[1] < b[0] or b[1] < a[0]):
        raise ValueError("ranges A and B overlap: shared noise would inflate the gain")


def run_and_camera(burst_dir_name: str) -> tuple[str, str]:
    m = re.fullmatch(r"(.+)_cam(\w+)", burst_dir_name)
    if not m:
        raise ValueError(f"{burst_dir_name}: not a <run_id>_cam<id> burst folder")
    return m.group(1), m.group(2)


def verdict(r: dict) -> dict:
    """r: camera, n, gain, predicted_gain, exactness, motion. Moved runs are not judged."""
    if r["motion"]["moved"]:
        return {"verdict": "moved", "checks": []}
    n, g, pred = r["n"], r["gain"], r["predicted_gain"]
    rel = abs(g - pred) / pred if pred else float("inf")
    checks = [
        check("Y16 equals the rounded double mean", r["exactness"]["ok"],
              r["exactness"].get("max_abs_error"), r["exactness"].get("threshold")),
        check("gain within 10 % of the autocorrelation prediction", rel <= PRED_REL_TOL,
              {"gain": round(g, 3), "predicted": round(pred, 3), "rel": round(rel, 3)}, PRED_REL_TOL),
    ]
    floor = USEFUL_FRACTION * n ** 0.5
    if r["camera"] == USEFUL_CAMERA:
        checks.append(check("gain >= 0.9 sqrt(N)", g >= floor, round(g, 3), round(floor, 3)))
    else:
        checks.append(check("gain vs sqrt(N) (recorded, no threshold)", True,
                            {"gain": round(g, 3), "sqrt_n": round(n ** 0.5, 3)}, None))
    ok = all(c["ok"] for c in checks)
    return {"verdict": "pass" if ok else "fail", "checks": checks}
