"""Parse the static camera metadata out of `adb shell dumpsys media.camera`.

The format (captured verbatim from a Note8 on LineageOS 20, fixtures/) is:

    == Camera HAL device device@3.3/legacy/0 (v3.3) static information: ==
          android.lens.facing (80005): byte[1]
            [BACK ]
          android.control.aeAvailableTargetFpsRanges (10014): int32[12]
            [15 15 24 24 ]
            [7 30 10 30 ]

A tag line is followed by one or more bracketed value lines. Values stay as string tokens;
rationals `(50 / 100)` become the single token `50/100`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER = re.compile(r"^== Camera HAL device \S*?/([^/\s]+) \(v[\d.]+\) static information: ==\s*$")
ANY_HEADER = re.compile(r"^== ")
TAG = re.compile(r"^\s+([A-Za-z][\w.]*) \(([0-9a-fA-F]+)\): (\w+)\[(\d+)\]\s*$")
VALUES = re.compile(r"^\s+\[(.*)\]\s*$")
RATIONAL = re.compile(r"\((-?\d+) / (-?\d+)\)")


@dataclass
class Entry:
    type: str
    count: int
    tokens: list[str] = field(default_factory=list)


def parse(text: str) -> dict[str, dict[str, Entry]]:
    """camera id -> tag name -> Entry, for every 'static information' block."""
    cameras: dict[str, dict[str, Entry]] = {}
    current: dict[str, Entry] | None = None
    entry: Entry | None = None
    for line in text.splitlines():
        if ANY_HEADER.match(line):
            m = HEADER.match(line)
            current = cameras.setdefault(m.group(1), {}) if m else None
            entry = None
            continue
        if current is None:
            continue
        t = TAG.match(line)
        if t:
            entry = Entry(t.group(3), int(t.group(4)))
            current[t.group(1)] = entry
            continue
        v = VALUES.match(line)
        if v and entry is not None:
            entry.tokens += RATIONAL.sub(r"\1/\2", v.group(1)).split()
        else:
            entry = None
    return cameras


def decode_byte_string_list(tokens: list[str]) -> list[str]:
    """Null-separated ASCII in a byte[] (e.g. logicalMultiCamera.physicalIds) -> strings."""
    out, cur = [], []
    for tok in tokens:
        code = int(tok)
        if code == 0:
            if cur:
                out.append("".join(cur))
            cur = []
        else:
            cur.append(chr(code))
    if cur:
        out.append("".join(cur))
    return out
