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


if __name__ == "__main__":
    unittest.main()
