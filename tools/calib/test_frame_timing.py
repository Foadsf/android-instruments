"""Tests for frame_timing.py (camera-calibration.md, frame timing amendment): on synthetic gyro and
frame data with a known exposure window it must find that window, and with blur unrelated to the
vibration it must say it cannot tell."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


def synthetic(window_ms, related=True, seed=3, seconds=12.0):
    """Gyro at 500 Hz: hand tremor (8-12 Hz) plus 60 ms vibration pulses (170 Hz) every 350-800 ms;
    frames at 30 fps whose sharpness drops with the vibration energy inside their true window
    [ts + window_ms[0], ts + window_ms[1]] (or, unrelated, with random dips)."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, 1 / 500)
    gyro = 0.03 * np.sin(2 * np.pi * rng.uniform(8, 12) * t)[:, None] * rng.normal(size=3)
    gyro = gyro + rng.normal(0, 0.004, (len(t), 3))
    p = 0.5
    while p < seconds - 0.2:
        on = (t >= p) & (t < p + 0.06)
        gyro[on] += 0.4 * np.sin(2 * np.pi * 170 * t[on])[:, None] * rng.normal(size=3)
        p += rng.uniform(0.35, 0.8)
    ts_g = (t * 1e9).astype(np.int64) + 10**12
    frames_t = np.arange(0.3, seconds - 0.3, 1 / 30)
    ts_f = (frames_t * 1e9).astype(np.int64) + 10**12
    import frame_timing as ft
    energy = ft.vibration_energy(ts_g, gyro)
    lo, hi = window_ms
    blur = np.array([energy[(ts_g >= f + lo * 1e6) & (ts_g < f + hi * 1e6)].mean() for f in ts_f])
    if not related:
        blur = rng.permutation(blur)
    sharp = 1000 * (1 - 0.6 * blur / blur.max()) * rng.normal(1, 0.02, len(ts_f))
    return ts_g, gyro, ts_f, sharp


class FrameTiming(unittest.TestCase):
    def test_recovers_a_window_before_the_stamp(self):  # the camera 2 bridge's case
        import frame_timing as ft
        r = ft.find_window(*synthetic((-90, -45)))
        self.assertTrue(r["ok"], r)
        self.assertLess(abs(r["start_ms"] + 90), 6, r)
        self.assertLess(abs(r["end_ms"] + 45), 10, r)

    def test_recovers_a_window_after_the_stamp(self):  # camera 0: exposure start + 8 ms + 32 ms skew
        import frame_timing as ft
        r = ft.find_window(*synthetic((0, 40), seed=4))
        self.assertTrue(r["ok"], r)
        self.assertLess(abs(r["start_ms"]), 6, r)
        self.assertLess(abs(r["end_ms"] - 40), 10, r)

    def test_the_control_window_is_that_of_the_centre_rows(self):
        # Sharpness is measured on the centre half: with a rolling shutter those rows are read from
        # a quarter to three quarters of the skew after the stamp, each exposed for the exposure.
        import frame_timing as ft
        self.assertEqual(ft.centre_window_ms(8.0, 32.0), (8.0, 32.0))
        self.assertEqual(ft.centre_window_ms(30.0, 32.0), (8.0, 54.0))

    def test_unrelated_blur_cannot_be_told(self):
        # Negative control: blur that does not follow the vibration must not yield a window.
        import frame_timing as ft
        r = ft.find_window(*synthetic((0, 40), related=False, seed=5))
        self.assertFalse(r["ok"], r)


if __name__ == "__main__":
    unittest.main()
