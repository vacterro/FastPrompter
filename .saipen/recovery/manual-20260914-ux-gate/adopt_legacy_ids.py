"""Record present-day adoption of BOARD IDs whose original allocations are absent.

This does not claim the original allocation happened or restore missing history.
"""

from datetime import datetime, timezone
from pathlib import Path


root = Path(__file__).resolve().parents[2]
log_path = root / "LOG.md"
state_path = root / "STATE.md"
board_path = root / "BOARD.md"
ids = (
    1260, 1261, 1262, 1257, 1258, 1263, 1264, 1259, 1246,
    1241, 1239, 1245, 1244, 1243, 1208, 800, 803,
)
board = board_path.read_text(encoding="utf-8")
for tid in ids:
    assert f"T-{tid} " in board

raw = log_path.read_bytes()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
assert b"[E-1901]" in raw and b"[E-1902]" not in raw
stamp = datetime.now(timezone.utc).strftime("%d.%m.%y %H:%M")
events = []
for event_id, tid in enumerate(ids, start=1902):
    events.append((
        f"- {stamp} [E-{event_id}] [parent: E-{event_id - 1}] "
        f"[T-{tid}] DEC: recovery adoption of existing BOARD identity; "
        "original allocation missing"
    ).encode("utf-8"))
log_path.write_bytes(raw + (b"" if raw.endswith(b"\n") else nl) + nl.join(events) + nl)

state_raw = state_path.read_bytes()
assert state_raw.count(b"last_event: 1901") == 1
state_path.write_bytes(state_raw.replace(b"last_event: 1901", b"last_event: 1918"))
