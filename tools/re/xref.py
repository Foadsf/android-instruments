"""String cross-references and function extraction for an arm64 ELF, using llvm-objdump output.

  xref.py strings <lib.so> <disasm.txt> <regex>     functions that reference strings matching regex
  xref.py func    <disasm.txt> <symbol-substring>   print the disassembly of matching functions
  xref.py calls   <disasm.txt> <symbol-substring>   callees (bl targets) of matching functions
Read-only.
"""
import re
import struct
import sys
from pathlib import Path

FUNC = re.compile(r"^([0-9a-f]+) <(.+)>:$")
ADRP = re.compile(r"([0-9a-f]+):\s+adrp\s+(x\d+), 0x([0-9a-f]+)")
ADD = re.compile(r"([0-9a-f]+):\s+add\s+(x\d+), (x\d+), #0x([0-9a-f]+)")
BL = re.compile(r"\sbl\s+0x[0-9a-f]+ <(.+?)>")


def sections(path: Path):
    data = path.read_bytes()
    shoff, = struct.unpack_from("<Q", data, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
    out = []
    for i in range(shnum):
        off = shoff + i * shentsize
        _, _, _, addr, foff, size = struct.unpack_from("<IIQQQQ", data, off)
        out.append((addr, foff, size))
    return data, out


def string_addrs(path: Path, pattern: re.Pattern):
    data, secs = sections(path)
    found = {}
    for m in re.finditer(rb"[\x20-\x7e]{4,}\x00", data):
        s = m.group()[:-1].decode()
        if not pattern.search(s):
            continue
        for addr, foff, size in secs:
            if addr and foff <= m.start() < foff + size:
                found[addr + m.start() - foff] = s
    return found


def iter_functions(disasm: Path):
    name, lines = None, []
    for line in disasm.read_text(encoding="utf-8", errors="replace").splitlines():
        m = FUNC.match(line)
        if m:
            if name:
                yield name, lines
            name, lines = m.group(2), []
        elif name:
            lines.append(line)
    if name:
        yield name, lines


def cmd_strings(lib, disasm, regex):
    targets = string_addrs(Path(lib), re.compile(regex))
    for name, lines in iter_functions(Path(disasm)):
        pages = {}
        hits = set()
        for line in lines:
            a = ADRP.search(line)
            if a:
                pages[a.group(2)] = int(a.group(3), 16)
                continue
            d = ADD.search(line)
            if d and d.group(3) in pages:
                addr = pages[d.group(3)] + int(d.group(4), 16)
                if addr in targets:
                    hits.add(targets[addr])
        for h in sorted(hits):
            print(f"{name}\t{h}")


def cmd_func(disasm, sub):
    for name, lines in iter_functions(Path(disasm)):
        if sub in name:
            print(f"== {name} ({len(lines)} lines)")
            print("\n".join(lines))


def cmd_calls(disasm, sub):
    for name, lines in iter_functions(Path(disasm)):
        if sub in name:
            calls = [m.group(1) for l in lines for m in [BL.search(l)] if m]
            print(f"== {name}: {len(calls)} calls")
            for c in dict.fromkeys(calls):
                print("   " + c)


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"strings": lambda: cmd_strings(*sys.argv[2:5]), "func": lambda: cmd_func(*sys.argv[2:4]),
     "calls": lambda: cmd_calls(*sys.argv[2:4])}[cmd]()
