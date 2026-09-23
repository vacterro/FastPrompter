"""One-off fallback for the invalid LOG tail; originals are beside this file."""

from datetime import datetime, timezone
from pathlib import Path


log_path = Path(__file__).resolve().parents[2] / "LOG.md"
raw = log_path.read_bytes()
newline = b"\r\n" if b"\r\n" in raw else b"\n"
lines = raw.splitlines(keepends=True)
parent_old = b"[E-1888] [parent: E-1887]"
parent_new = b"[E-1888] [parent: E-1884]"
assert sum(parent_old in line for line in lines) == 1
assert sum(line.startswith(b"H 2026-09-13 hunt3 sweep:") for line in lines) == 1
assert any(b"[E-1884]" in line for line in lines)
assert any(b"[E-1897]" in line for line in lines)
assert not any(b"[E-1898]" in line for line in lines)

repaired = []
for line in lines:
    if line.startswith(b"H 2026-09-13 hunt3 sweep:"):
        continue  # Exact original survives in LOG.original.md.
    repaired.append(line.replace(parent_old, parent_new))

stamp = datetime.now(timezone.utc).strftime("%d.%m.%y %H:%M")
event = (
    f"- {stamp} [E-1898] [parent: E-1897] DEC: recovery fallback -- "
    "archived malformed H line; E-1888 parent changed from absent E-1887 "
    "to extant E-1884; missing E-1885..1887 remain unknown; mechanical "
    "recover refused history-void"
).encode("utf-8")
if repaired[-1].endswith((b"\n", b"\r")):
    repaired.append(event + newline)
else:
    repaired.append(newline + event + newline)
log_path.write_bytes(b"".join(repaired))
