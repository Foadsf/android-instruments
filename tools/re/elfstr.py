"""Print the NUL-terminated string at each virtual address: elfstr.py <lib.so> 0xADDR ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xref  # noqa: E402

data, secs = xref.sections(Path(sys.argv[1]))
for a in sys.argv[2:]:
    va = int(a, 16)
    for addr, foff, size in secs:
        if addr and addr <= va < addr + size:
            off = foff + va - addr
            end = data.index(b"\x00", off)
            print(f"{a}: {data[off:end][:160].decode('ascii', errors='replace')!r}")
            break
    else:
        print(f"{a}: not in any section")
