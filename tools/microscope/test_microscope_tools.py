"""Tests for the microscope-live host tools: report checks, NumPy sharpness, NCC scale search."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_checks as lc  # noqa: E402

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
HAS_CV2 = HAS_NUMPY and importlib.util.find_spec("cv2") is not None


def good_camera(fps=29.5, n=16):
    period = int(1e9 / fps)
    return {"camera_id": "2", "width": 1440, "height": 1080,
            "stream": {"frames": 295, "elapsed_s": 10.0, "fps": fps, "capture_failures": 0},
            "burst": {"frames": n, "complete": True, "timestamps_ns": [1000 + i * period for i in range(n)]}}


class ReportChecks(unittest.TestCase):
    def test_a_good_run_passes(self):
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [good_camera()]})["verdict"], "pass")

    def test_slow_stream_fails(self):
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [good_camera(fps=12.0)]})["verdict"], "fail")

    def test_frame_rate_is_judged_only_on_camera_2(self):
        wide = good_camera(fps=12.0)
        wide["camera_id"] = "0"
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [wide, good_camera()]})["verdict"], "pass")
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [wide, good_camera(fps=12.0)]})["verdict"], "fail")

    def test_a_dropped_stretch_in_the_burst_fails(self):
        cam = good_camera()
        ts = cam["burst"]["timestamps_ns"]
        cam["burst"]["timestamps_ns"] = ts[:8] + [t + 4 * (ts[1] - ts[0]) for t in ts[8:]]  # 4 frames missing
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [cam]})["verdict"], "fail")

    def test_non_increasing_timestamps_fail(self):
        cam = good_camera()
        cam["burst"]["timestamps_ns"][5] = cam["burst"]["timestamps_ns"][4]
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [cam]})["verdict"], "fail")

    def test_short_burst_and_camera_error_and_empty_report_fail(self):
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [good_camera(n=10)]})["verdict"], "fail")
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": [{"camera_id": "9", "error": "x"}]})["verdict"], "fail")
        self.assertEqual(lc.verdict({"burst_frames": 16, "cameras": []})["verdict"], "fail")


@unittest.skipUnless(HAS_NUMPY, "numpy not installed")
class SharpnessReference(unittest.TestCase):
    def test_single_bright_pixel_matches_the_hand_calculation(self):
        import numpy as np
        luma = np.zeros((20, 20), dtype=np.uint8)  # centre half is rows/cols 5..14, interior 6..13
        luma[9, 9] = 10
        # Laplacian 40 at the pixel and -10 at its four neighbours, over an 8x8 interior
        self.assertAlmostEqual(lc.sharpness_np(luma), (1600 + 4 * 100) / 64)

    def test_flat_is_zero_and_crosscheck_reads_i420(self):
        import numpy as np
        w, h = 16, 12
        rng = np.random.default_rng(3)
        frame = rng.integers(0, 256, w * h * 3 // 2, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as d:
            frame.tofile(Path(d) / "frame_00.yuv")
            host = lc.sharpness_np(frame[: w * h].reshape(h, w))
            ok = lc.sharpness_crosscheck(Path(d), {"width": w, "height": h, "sharpness_frame0": host})
            bad = lc.sharpness_crosscheck(Path(d), {"width": w, "height": h, "sharpness_frame0": host * 1.05})
        self.assertTrue(ok["ok"])
        self.assertFalse(bad["ok"])  # negative control: 5 % off must fail the 1 % tolerance
        self.assertEqual(lc.sharpness_np(np.full((h, w), 77, dtype=np.uint8)), 0.0)


@unittest.skipUnless(HAS_CV2, "opencv not installed")
class NccScale(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        rng = np.random.default_rng(5)
        noise = rng.random((300, 400)).astype(np.float32) * 255
        self.ref = cv2.GaussianBlur(noise, (0, 0), 3)

    def magnified(self, s):
        import cv2
        h, w = self.ref.shape
        cw, ch = int(w / s), int(h / s)
        crop = self.ref[(h - ch) // 2:(h - ch) // 2 + ch, (w - cw) // 2:(w - cw) // 2 + cw]
        return cv2.resize(crop, (w, h), interpolation=cv2.INTER_CUBIC)

    def test_recovers_a_known_magnification(self):
        import ncc_scale
        s, ncc = ncc_scale.best_scale(self.ref, self.magnified(1.5))
        self.assertAlmostEqual(s, 1.5, delta=0.03)
        self.assertGreater(ncc, 0.9)

    def test_unrelated_image_has_low_ncc(self):
        import numpy as np
        import ncc_scale
        other = np.random.default_rng(9).random(self.ref.shape).astype(np.float32) * 255
        _, ncc = ncc_scale.best_scale(self.ref, other)
        self.assertLess(ncc, 0.5)


class StartArgs(unittest.TestCase):
    def test_torch_is_passed_and_defaults_to_off(self):
        import run_live
        a = run_live.start_args("r1", "0,2", 4000, 32, "mode")
        self.assertEqual(a[a.index("torch") - 1: a.index("torch") + 2], ["--es", "torch", "mode"])
        b = run_live.start_args("r1", None, 4000, 16)
        self.assertEqual(b[b.index("torch") + 1], "off")
        self.assertEqual(b[b.index("ois") + 1], "default")
        self.assertNotIn("cameras", b)
        c = run_live.start_args("r1", "0", 4000, 16, ois="off")
        self.assertEqual(c[c.index("ois") + 1], "off")
        self.assertNotIn("series", c)

    def test_series_extras_are_passed_only_for_a_series(self):
        import run_live
        a = run_live.start_args("r1", "0,2", 800, 4, ois="off", series=15, still_ms=1200, focus=3.5)
        self.assertEqual(a[a.index("series") - 1: a.index("series") + 2], ["--ei", "series", "15"])
        self.assertEqual(a[a.index("still_ms") + 1], "1200")
        self.assertEqual(a[a.index("focus_diopters") - 1: a.index("focus_diopters") + 2], ["--ef", "focus_diopters", "3.5"])
        b = run_live.start_args("r1", "0,2", 800, 4, series=3)
        self.assertNotIn("focus_diopters", b)

    def test_scale_extras_and_nothing_else(self):
        import run_live
        a = run_live.start_args("r1", "0", 800, 4, scale=3, gap_ms=5000, sweep=30, focus=2.0)
        self.assertEqual(a[a.index("scale_bursts") - 1: a.index("scale_bursts") + 2], ["--ei", "scale_bursts", "3"])
        self.assertEqual(a[a.index("gap_ms") + 1], "5000")
        self.assertNotIn("sweep", a)
        self.assertNotIn("focus_diopters", a)
        self.assertNotIn("scale_bursts", run_live.start_args("r1", "0", 800, 4))

    def test_sweep_extras_are_passed_only_for_a_sweep(self):
        import run_live
        a = run_live.start_args("r1", "0,2", 800, 4, ois="off", focus=2.0,
                                sweep=30, gate="0:0.04,2:0.02", max_exposure_us=8000)
        self.assertEqual(a[a.index("sweep") - 1: a.index("sweep") + 2], ["--ei", "sweep", "30"])
        self.assertEqual(a[a.index("gate_rad_s") - 1: a.index("gate_rad_s") + 2],
                         ["--es", "gate_rad_s", "0:0.04,2:0.02"])
        self.assertEqual(a[a.index("max_exposure_us") - 1: a.index("max_exposure_us") + 2],
                         ["--el", "max_exposure_us", "8000"])
        self.assertEqual(a[a.index("focus_diopters") + 1], "2.0")
        self.assertNotIn("series", a)
        b = run_live.start_args("r1", "0,2", 800, 4, series=3)
        self.assertNotIn("sweep", b)

    def test_timing_extra_is_passed_only_for_a_timing_run(self):
        import run_live
        a = run_live.start_args("r1", "0,2", 800, 4, timing=12, max_exposure_us=8000)
        self.assertEqual(a[a.index("timing") - 1: a.index("timing") + 2], ["--ei", "timing", "12"])
        self.assertEqual(a[a.index("max_exposure_us") + 1], "8000")  # the control runs as the sweep does
        self.assertNotIn("sweep", a)
        self.assertNotIn("timing", run_live.start_args("r1", "0,2", 800, 4, sweep=30))

    def test_a_measured_bridge_window_is_passed_to_the_sweep_only_if_trusted(self):
        import run_live
        a = run_live.start_args("r1", "0,2", 800, 4, sweep=30, bridge_window="-70,-20")
        self.assertEqual(a[a.index("bridge_window_ms") - 1: a.index("bridge_window_ms") + 2],
                         ["--es", "bridge_window_ms", "-70,-20"])
        self.assertNotIn("bridge_window_ms", run_live.start_args("r1", "0,2", 800, 4, sweep=30))
        self.assertEqual(run_live.bridge_window_from({"ok": True, "start_ms": -70, "end_ms": -20}), "-70,-20")
        # Not trusted: no window (the sweep keeps its 150 ms default), and never one after the stamp.
        self.assertIsNone(run_live.bridge_window_from({"ok": False, "start_ms": -70, "end_ms": -20}))
        self.assertIsNone(run_live.bridge_window_from({"ok": True, "start_ms": -10, "end_ms": 30}))

    def test_gates_parse_per_camera_and_refuse_nonsense(self):
        import run_live
        self.assertEqual(run_live.parse_gates("0:0.04,2:0.02"), {"0": 0.04, "2": 0.02})
        for bad in ("0.04", "0:", "0:-1", "0:0.04,0:0.02", "0:abc"):
            with self.assertRaises(ValueError, msg=bad):
                run_live.parse_gates(bad)


if __name__ == "__main__":
    unittest.main()
