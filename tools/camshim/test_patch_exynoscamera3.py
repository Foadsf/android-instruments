"""Tests for patch_exynoscamera3.py on synthetic images (the real library is not committed)."""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch_exynoscamera3 as p  # noqa: E402


def synthetic() -> bytes:
    img = bytearray(0xA0000)
    for off, old, _new, _what in p.PATCHES:
        img[off:off + len(old)] = old
    return bytes(img)


class Patch(unittest.TestCase):
    def test_patches_exactly_the_listed_bytes(self):
        src = synthetic()
        out = p.patch(src, hashlib.sha256(src).hexdigest())
        self.assertEqual(len(out), len(src))
        diff = [i for i in range(len(src)) if src[i] != out[i]]
        self.assertEqual(diff, [off for off, *_ in p.PATCHES])
        for off, _old, new, _what in p.PATCHES:
            self.assertEqual(out[off:off + 2], new)

    def test_refuses_a_different_build(self):
        with self.assertRaises(p.Refused):
            p.patch(synthetic())  # hash is not the analysed build's

    def test_refuses_when_original_bytes_are_missing(self):
        src = bytearray(synthetic())
        src[p.PATCHES[1][0]] = 0x09
        with self.assertRaises(p.Refused):
            p.patch(bytes(src), hashlib.sha256(bytes(src)).hexdigest())

    def test_patched_value_is_movs_imm5(self):
        # Thumb T1 MOVS Rd,#imm8 is 0b00100 Rd imm8: low byte = imm8, high byte = 0x20 | Rd.
        for _off, old, new, _what in p.PATCHES:
            self.assertEqual((old[0], new[0], old[1], new[1] & 0xF8), (7, 5, new[1], 0x20))


if __name__ == "__main__":
    unittest.main()
