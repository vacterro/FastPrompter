"""Archive legacy letter-suffixed Work rows rejected by the current grammar."""

from datetime import datetime, timezone
from pathlib import Path
import re


root = Path(__file__).resolve().parents[2]
board_path = root / "BOARD.md"
log_path = root / "LOG.md"
state_path = root / "STATE.md"
raw = board_path.read_bytes()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
lines = raw.splitlines(keepends=True)
legacy = [line for line in lines if re.match(rb"^- \[[ x/]\] T-1238-[A-I] ", line)]
assert len(legacy) == 9, len(legacy)
(Path(__file__).parent / "legacy_T-1238_children.md").write_bytes(b"".join(legacy))
board_path.write_bytes(b"".join(line for line in lines if line not in legacy))

stamp = datetime.now(timezone.utc)
log_raw = log_path.read_bytes()
log_nl = b"\r\n" if b"\r\n" in log_raw else b"\n"
assert b"[E-1899]" in log_raw and b"[E-1900]" not in log_raw
event = (
    f"- {stamp:%d.%m.%y %H:%M} [E-1900] [parent: E-1899] DEC: recovery fallback -- "
    "archived nine legacy T-1238 letter-suffixed child rows rejected by "
    "current BOARD grammar; parent T-1238 and exact originals retained"
).encode("utf-8")
log_path.write_bytes(log_raw + (b"" if log_raw.endswith(b"\n") else log_nl) + event + log_nl)

state_raw = state_path.read_bytes()
assert state_raw.count(b"last_event: 1899") == 1
state_path.write_bytes(state_raw.replace(b"last_event: 1899", b"last_event: 1900"))
