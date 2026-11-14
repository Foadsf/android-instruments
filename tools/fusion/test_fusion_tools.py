"""Tests for the burst_merge evaluator (docs/units/burst-merge.md), on synthetic frames made here."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_checks as mc  # noqa: E402

HAS_NUMPY = importlib.util.find_spec("numpy") is not None


def stack(n=16, h=96, w=128, sigma=4.0, rho=0.0, seed=1, textured=True, drift=0.0):
    """n frames of a static scene plus noise; rho > 0 gives AR(1) noise across frames; drift moves
    the scene smoothly by that many pixels (vertically) over the burst, rendered analytically."""
    import numpy as np
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(float)

    def scene(dy):
        if not textured:
            return 128 + 0 * xx
        y = yy - dy
        return 128 + 40 * np.sin(0.21 * xx) * np.cos(0.13 * y) + 15 * np.sin(0.05 * (xx + 2 * y))

    noise = rng.normal(0, sigma, (h, w))
    out = []
    for i in range(n):
        out.append(scene(drift * (i / max(n - 1, 1) - 0.5)) + noise)
        noise = rho * noise + np.sqrt(1 - rho * rho) * rng.normal(0, sigma, (h, w))
    return np.stack(out)


@unittest.skipUnless(HAS_NUMPY, "numpy not installed")
class GainAndPrediction(unittest.TestCase):
    def test_independent_noise_gives_sqrt_n(self):
        s = stack(16, 256, 256)
        g = mc.gain(s[0], s[8], s[:8].mean(0), s[8:].mean(0))
        self.assertAlmostEqual(g, 8 ** 0.5, delta=0.05 * 8 ** 0.5)
        pred = mc.predicted_gain(mc.variogram(s), list(range(8)), list(range(8, 16)))
        self.assertAlmostEqual(pred, 8 ** 0.5, delta=0.05 * 8 ** 0.5)

    def test_correlated_noise_lowers_gain_and_prediction_follows(self):
        s = stack(32, 256, 256, rho=0.4, seed=3)
        g = mc.gain(s[0], s[16], s[:16].mean(0), s[16:].mean(0))
        pred = mc.predicted_gain(mc.variogram(s), list(range(16)), list(range(16, 32)))
        self.assertLess(g, 0.8 * 4.0)
        self.assertAlmostEqual(g, pred, delta=0.10 * pred)
        rho = mc.lag_correlation(mc.variogram(s), 16)
        self.assertAlmostEqual(rho[0], 0.4, delta=0.05)

    def test_a_merge_that_drops_half_its_frames_misses_the_prediction(self):
        s = stack(32, 256, 256, seed=5)
        g = mc.gain(s[0], s[16], s[:8].mean(0), s[16:24].mean(0))  # "merged 16" but used 8
        pred = mc.predicted_gain(mc.variogram(s), list(range(16)), list(range(16, 32)))
        self.assertGreater(abs(g - pred) / pred, 0.10)

    def test_copies_give_no_gain(self):
        s = stack(16, 128, 128)
        a = s[0]
        b = s[8]
        self.assertAlmostEqual(mc.gain(a, b, a, b), 1.0, places=6)

    def test_global_offset_between_halves_is_not_noise(self):
        s = stack(16, 128, 128)
        g0 = mc.gain(s[0], s[8], s[:8].mean(0), s[8:].mean(0))
        g1 = mc.gain(s[0], s[8] + 5, s[:8].mean(0), s[8:].mean(0) + 5)
        self.assertAlmostEqual(g0, g1, places=9)


@unittest.skipUnless(HAS_NUMPY, "numpy not installed")
class MotionLightingExactness(unittest.TestCase):
    def test_still_halves_are_not_moved(self):
        s = stack(16, 128, 128)
        m = mc.motion(s[:8].mean(0), s[8:].mean(0))
        self.assertEqual(m["shift"], [0, 0])
        self.assertFalse(m["moved"])

    def test_a_three_pixel_shift_is_marked_moved(self):
        import numpy as np
        s = stack(16, 128, 128)
        m = mc.motion(s[:8].mean(0), np.roll(s[8:].mean(0), 3, axis=1))
        self.assertTrue(m["moved"])
        self.assertEqual(abs(m["shift"][1]), 3)

    def test_a_featureless_scene_cannot_prove_stillness(self):
        s = stack(16, 128, 128, textured=False)
        self.assertTrue(mc.motion(s[:8].mean(0), s[8:].mean(0))["moved"])

    def test_a_smooth_subpixel_drift_is_marked_moved(self):
        s = stack(32, 128, 160, drift=0.8, seed=4)
        self.assertFalse(mc.motion(s[:16].mean(0), s[16:].mean(0))["moved"])  # integer check misses it
        sp = mc.subpixel(s)
        self.assertTrue(sp["moved"])
        self.assertAlmostEqual(sp["shift_ptp_px"][1], 0.8, delta=0.15)

    def test_a_still_burst_is_not_moved_at_subpixel_level(self):
        sp = mc.subpixel(stack(32, 128, 160, seed=6))
        self.assertFalse(sp["moved"])
        self.assertLess(sp["motion_share"], mc.MAX_MOTION_SHARE)

    def test_torch_that_did_not_raise_the_luma_is_not_shown_lit(self):
        self.assertEqual(mc.lighting(40.0, 30.0)["status"], "not shown")
        self.assertEqual(mc.lighting(60.0, 30.0)["status"], "lit")

    def test_an_exposure_drop_shows_the_torch_lit_when_ae_hides_it_in_the_luma(self):
        self.assertEqual(mc.lighting(185.6, 169.5, 4_521_000, 39_981_000)["status"], "lit")
        self.assertEqual(mc.lighting(185.6, 169.5, 39_000_000, 39_981_000)["status"], "not shown")

    def test_exactness_check_catches_a_one_lsb_error(self):
        import numpy as np
        s = np.round(stack(4, 32, 32)).clip(0, 255)
        y16 = np.floor(256 * s.mean(0) + 0.5).astype(np.uint16)
        self.assertTrue(mc.exactness(s, y16)["ok"])
        y16[5, 5] += 1
        self.assertFalse(mc.exactness(s, y16)["ok"])


class Ranges(unittest.TestCase):
    def test_default_halves_are_disjoint(self):
        self.assertEqual(mc.default_ranges(16), ((0, 7), (8, 15)))
        self.assertEqual(mc.default_ranges(32), ((0, 15), (16, 31)))

    def test_overlapping_ranges_are_refused(self):
        with self.assertRaises(ValueError):
            mc.check_ranges((0, 8), (8, 15), 16)
        with self.assertRaises(ValueError):
            mc.check_ranges((0, 7), (8, 14), 16)  # unequal lengths
        with self.assertRaises(ValueError):
            mc.check_ranges((0, 7), (8, 16), 16)  # beyond the burst

    def test_burst_dir_names_give_run_and_camera(self):
        self.assertEqual(mc.run_and_camera("175526-0da1_cam2"), ("175526-0da1", "2"))
        with self.assertRaises(ValueError):
            mc.run_and_camera("captures")


class Verdict(unittest.TestCase):
    def base(self, cam="0", g=2.7, pred=2.8, n=8):
        return {"camera": cam, "n": n, "gain": g, "predicted_gain": pred,
                "exactness": {"ok": True}, "motion": {"moved": False}}

    def test_camera_0_with_full_gain_passes(self):
        self.assertEqual(mc.verdict(self.base())["verdict"], "pass")

    def test_camera_0_below_ninety_percent_of_sqrt_n_fails(self):
        self.assertEqual(mc.verdict(self.base(g=2.3, pred=2.35))["verdict"], "fail")

    def test_gain_off_its_prediction_fails(self):
        self.assertEqual(mc.verdict(self.base(cam="2", g=1.5, pred=2.2))["verdict"], "fail")

    def test_camera_2_below_sqrt_n_is_recorded_not_failed(self):
        self.assertEqual(mc.verdict(self.base(cam="2", g=2.1, pred=2.2))["verdict"], "pass")

    def test_moved_is_not_judged(self):
        r = self.base()
        r["motion"] = {"moved": True}
        self.assertEqual(mc.verdict(r)["verdict"], "moved")


@unittest.skipUnless(HAS_NUMPY, "numpy not installed")
class EvaluatorRefusesOverlap(unittest.TestCase):
    def test_pgm_whose_data_starts_with_whitespace_bytes_reads_back(self):
        import numpy as np
        import burst_merge_eval as ev
        img = np.array([[0x0A20, 0x0920], [0x2000, 0xFFFF]], dtype=">u2")  # newline, tab, space bytes
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.pgm"
            p.write_bytes(b"P5\n2 2\n65535\n" + img.tobytes())
            self.assertTrue(np.array_equal(ev.read_pgm16(p), img))

    def test_overlapping_ranges_exit_2(self):
        import burst_merge_eval as ev
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "000000-test_cam0"
            b.mkdir()
            (b / "burst.json").write_text(json.dumps({"width": 4, "height": 2, "frames": 5}))
            self.assertEqual(ev.main([str(b), "--frames-a", "0-2", "--frames-b", "2-4"]), 2)


if __name__ == "__main__":
    unittest.main()
