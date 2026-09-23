"""Declare the evidenced E-1884 to E-1888 historical gap without fabrication."""

from datetime import datetime, timezone
from pathlib import Path


root = Path(__file__).resolve().parents[2]
log_path = root / "LOG.md"
state_path = root / "STATE.md"
raw = log_path.read_bytes()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
assert b"[E-1918]" in raw and b"[E-1919]" not in raw
stamp = datetime.now(timezone.utc).strftime("%d.%m.%y %H:%M")
event = (
    f"- {stamp} [E-1919] [parent: E-1918] DEC: "
    "LEDGER-GAP AMNESTY E-1884 -> E-1888; E-1885..1887 absent from the "
    "complete ledger, original checkpoint preserved in recovery"
).encode("utf-8")
log_path.write_bytes(raw + (b"" if raw.endswith(b"\n") else nl) + event + nl)
state_raw = state_path.read_bytes()
assert state_raw.count(b"last_event: 1918") == 1
state_path.write_bytes(state_raw.replace(b"last_event: 1918", b"last_event: 1919"))
