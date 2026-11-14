"""Tests for the calibration target: the generated PDF passes the independent checker, and PDFs
whose drawing disagrees with their spec fail it (negative controls)."""
import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

NEEDED = ("numpy", "cv2", "matplotlib", "fitz")
HAS_ALL = all(importlib.util.find_spec(m) is not None for m in NEEDED)


@unittest.skipUnless(HAS_ALL, "needs " + ", ".join(NEEDED))
class Target(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import make_target as mt
        cls.mt = mt
        cls.tmp = tempfile.TemporaryDirectory()
        cls.good = Path(cls.tmp.name) / "good.pdf"
        mt.build(mt.default_spec(), cls.good)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verdict(self, pdf, spec):
        import check_target as ct
        r = ct.evaluate(pdf, spec, 300)
        return r["verdict"], {c["check"]: c["ok"] for c in r["checks"]}

    def drawn_with(self, change):
        spec = copy.deepcopy(self.mt.default_spec())
        change(spec)
        pdf = Path(self.tmp.name) / f"bad_{id(change)}.pdf"
        self.mt.build(spec, pdf)
        return pdf

    def test_generated_target_passes(self):
        v, checks = self.verdict(self.good, self.mt.default_spec())
        self.assertEqual(v, "pass", checks)

    def test_a_board_drawn_small_fails_the_corner_check(self):
        pdf = self.drawn_with(lambda s: s["board"].update(square_mm=19.5, marker_mm=13.65))
        v, checks = self.verdict(pdf, self.mt.default_spec())
        self.assertEqual(v, "fail")
        self.assertFalse(checks["corner position vs spec, max (mm)"])

    def test_a_board_drawn_one_mm_off_fails(self):
        pdf = self.drawn_with(lambda s: s["board"].update(origin_mm=[16.0, 22.0]))
        _, checks = self.verdict(pdf, self.mt.default_spec())
        self.assertFalse(checks["corner position vs spec, max (mm)"])

    def test_a_short_ruler_fails(self):
        pdf = self.drawn_with(lambda s: s["ruler"].update(length_mm=148.0))
        _, checks = self.verdict(pdf, self.mt.default_spec())
        self.assertFalse(checks["ruler line spans exactly its length"])

    def test_a_flatter_edge_fails_the_angle_check(self):
        pdf = self.drawn_with(lambda s: s["slanted_edge"].update(angle_deg=4.0))
        _, checks = self.verdict(pdf, self.mt.default_spec())
        self.assertFalse(checks["slanted edge angle (deg)"])

    def test_runs_merge_into_rectangles_that_cover_the_bitmap_exactly(self):
        import numpy as np
        rng = np.random.default_rng(1)
        mask = rng.random((40, 50)) > 0.5
        mask[5:20, 10:30] = True
        back = np.zeros_like(mask)
        for x, y, w, h in self.mt.runs_to_rects(mask):
            self.assertFalse(back[y:y + h, x:x + w].any())  # no overlap
            back[y:y + h, x:x + w] = True
        self.assertTrue(np.array_equal(back, mask))


if __name__ == "__main__":
    unittest.main()
