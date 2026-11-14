"""Tests for the Android sparse-image expander on hand-built images."""
import io
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import samsung_system_image as s  # noqa: E402

BLK = 4096


def sparse(chunks, total_blocks):
    out = struct.pack("<IHHHHIIII", s.SPARSE_MAGIC, 1, 0, 28, 12, BLK, total_blocks, len(chunks), 0)
    for ctype, blocks, payload in chunks:
        out += struct.pack("<HHII", ctype, 0, blocks, 12 + len(payload)) + payload
    return out


class Unsparse(unittest.TestCase):
    def test_raw_fill_and_dont_care(self):
        img = sparse([(s.CHUNK_RAW, 1, b"A" * BLK), (s.CHUNK_FILL, 2, b"\x01\x02\x03\x04"),
                      (s.CHUNK_DONT_CARE, 1, b""), (s.CHUNK_CRC32, 0, b"\0\0\0\0")], 4)
        dst = io.BytesIO()
        self.assertEqual(s.unsparse(io.BytesIO(img), dst), 4 * BLK)
        data = dst.getvalue()
        self.assertEqual(len(data), 4 * BLK)
        self.assertEqual(data[:BLK], b"A" * BLK)
        self.assertEqual(data[BLK:3 * BLK], b"\x01\x02\x03\x04" * (2 * BLK // 4))
        self.assertEqual(data[3 * BLK:], b"\0" * BLK)

    def test_rejects_wrong_magic_and_truncation(self):
        with self.assertRaises(s.SparseError):
            s.unsparse(io.BytesIO(b"\0" * 28), io.BytesIO())
        img = sparse([(s.CHUNK_RAW, 1, b"A" * BLK)], 1)
        with self.assertRaises(s.SparseError):
            s.unsparse(io.BytesIO(img[:-100]), io.BytesIO())

    def test_rejects_block_count_mismatch(self):
        img = sparse([(s.CHUNK_RAW, 1, b"A" * BLK)], 2)
        with self.assertRaises(s.SparseError):
            s.unsparse(io.BytesIO(img), io.BytesIO())


if __name__ == "__main__":
    unittest.main()
