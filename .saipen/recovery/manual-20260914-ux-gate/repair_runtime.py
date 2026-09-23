"""Fallback for unambiguous BOARD/STATE runtime drift after history repair."""

from datetime import datetime, timezone
from pathlib import Path


root = Path(__file__).resolve().parents[2]
board_path = root / "BOARD.md"
state_path = root / "STATE.md"
log_path = root / "LOG.md"
raw = board_path.read_bytes()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
lines = raw.splitlines(keepends=True)
t1239 = [line for line in lines if line.startswith(b"- [ ] T-1239 ")]
assert len(t1239) == 1
assert lines.index(t1239[0]) > next(i for i, line in enumerate(lines) if line.startswith(b"## BLOCKED"))
lines.remove(t1239[0])
done_at = next(i for i, line in enumerate(lines) if line.startswith(b"## DONE"))
lines.insert(done_at, t1239[0])
for i, line in enumerate(lines):
    if line.startswith(b"- [x] T-1254 "):
        old = b"claim_time: 2026-09-11T21:40:00Z; ship E-1884 commit afc569b pushed (i18n payload + repair, no version bump)"
        assert line.count(old) == 1
        line = line.replace(old, b"claim_time: 2026-09-11T21:40:00Z")
        line = line.replace(b" | verify: ", b" | verify: ship E-1884 commit afc569b pushed (i18n payload + repair, no version bump); ", 1)
        lines[i] = line
board_path.write_bytes(b"".join(lines))

stamp = datetime.now(timezone.utc)
log_raw = log_path.read_bytes()
log_nl = b"\r\n" if b"\r\n" in log_raw else b"\n"
assert b"[E-1900]" in log_raw and b"[E-1901]" not in log_raw
event = (
    f"- {stamp:%d.%m.%y %H:%M} [E-1901] [parent: E-1900] DEC: recovery fallback -- "
    "moved triaged unblocked T-1239 to TODO, restored T-1254 UTC claim_time, "
    "and set HUNT task none; originals retained in recovery"
).encode("utf-8")
log_path.write_bytes(log_raw + (b"" if log_raw.endswith(b"\n") else log_nl) + event + log_nl)

state_raw = state_path.read_bytes()
assert state_raw.count(b"last_event: 1900") == 1
assert state_raw.count(b"task: T-1256 (closed) -> HUNT sweep") == 1
state_raw = state_raw.replace(b"last_event: 1900", b"last_event: 1901")
state_raw = state_raw.replace(b"task: T-1256 (closed) -> HUNT sweep", b"task: none")
state_path.write_bytes(state_raw)
