"""Probes: cheap ways to ask whether an agent has stopped working.

Every probe answers one question — "does this look idle right now?" — and
the engine only acts when all of them agree for a sustained window.

Two rules run through the whole file:

* **Uncertainty is not idleness.** A missing file, an unreadable database, a
  probe whose optional dependency is not installed: all report BUSY. The
  cost of a wrong "idle" is a prompt typed into a running agent; the cost of
  a wrong "busy" is waiting a bit longer.
* **The clock is an argument.** Nothing here calls time.time() on its own,
  so the quiet-window logic is testable without sleeping.
"""

from __future__ import annotations

import glob
import json
import os

IDLE = "idle"
BUSY = "busy"
UNSUPPORTED = "unsupported"     # cannot run at all; treated as busy


class Probe:
    """One signal. Subclasses implement `_read`."""

    kind = "probe"

    def __init__(self, quiet_ms=2000, name=""):
        try:
            self.quiet_ms = max(0, int(quiet_ms))
        except (TypeError, ValueError):
            self.quiet_ms = 2000
        self.name = name or self.kind
        self._last_token = None
        self._changed_at = None
        self.reason = ""

    # ---- to implement --------------------------------------------------
    def _read(self):
        """A token that changes whenever the target is doing something.

        Return None when the signal cannot be read at all.
        """
        raise NotImplementedError

    # ---- the shared quiet-window logic ---------------------------------
    def poll(self, now):
        """(state, reason) at time `now` (seconds, monotonic or wall)."""
        try:
            token = self._read()
        except Exception as exc:                  # a probe must never raise
            self.reason = f"{self.kind} failed: {exc}"
            self._last_token = None
            self._changed_at = now
            return BUSY, self.reason

        if token is None:
            self.reason = f"{self.kind}: nothing to read"
            self._last_token = None
            self._changed_at = now
            return BUSY, self.reason

        if token != self._last_token:
            self._last_token = token
            self._changed_at = now
            self.reason = f"{self.kind}: changed"
            return BUSY, self.reason

        quiet_for = (now - (self._changed_at if self._changed_at is not None else now))
        if quiet_for * 1000.0 >= self.quiet_ms:
            self.reason = f"{self.kind}: quiet for {quiet_for:.1f}s"
            return IDLE, self.reason
        self.reason = f"{self.kind}: settling ({quiet_for:.1f}s)"
        return BUSY, self.reason

    def idle(self, now):
        return self.poll(now)[0] == IDLE

    def reset(self):
        self._last_token = None
        self._changed_at = None


class FileProbe(Probe):
    """Watches the newest file matching a glob.

    Built for Claude Code, which appends its session transcript live to
    ~/.claude/projects/<slug>/<uuid>.jsonl.
    """

    kind = "file"

    def __init__(self, pattern, quiet_ms=2000, newest=True,
                 last_line_json=None, ignore_types=(), name=""):
        super().__init__(quiet_ms, name)
        self.pattern = pattern or ""
        self.newest = bool(newest)
        self.last_line_json = last_line_json or None
        self.ignore_types = tuple(ignore_types or ())

    def _path(self):
        expanded = os.path.expanduser(os.path.expandvars(self.pattern))
        matches = [p for p in glob.glob(expanded) if os.path.isfile(p)]
        if not matches:
            return None
        if self.newest:
            return max(matches, key=os.path.getmtime)
        return sorted(matches)[0]

    def _read(self):
        path = self._path()
        if path is None:
            return None
        stat = os.stat(path)
        return (path, stat.st_size, round(stat.st_mtime, 3))

    def poll(self, now):
        state, reason = super().poll(now)
        if state != IDLE or not self.last_line_json:
            return state, reason
        # The file has gone quiet, but quiet is not finished: a turn paused
        # on a tool call looks exactly the same. Require the last line that
        # carries content to be the shape the adapter says means "done".
        ok, why = self._tail_matches()
        if not ok:
            self.reason = f"{self.kind}: {why}"
            return BUSY, self.reason
        return IDLE, reason

    def _tail_matches(self, window=65536):
        path = self._path()
        if path is None:
            return False, "nothing to read"
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - window))
                chunk = fh.read().decode("utf-8", errors="replace")
        except OSError as exc:
            return False, f"unreadable ({exc})"

        for line in reversed(chunk.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue           # a partial first line from the window cut
            if not isinstance(entry, dict):
                continue
            # metadata lines (custom-title, ai-title, mode...) are not the
            # end of a turn and must not be mistaken for one
            if entry.get("type") in self.ignore_types:
                continue
            for key, want in self.last_line_json.items():
                if entry.get(key) != want:
                    return False, f"last entry is {entry.get(key)!r}, not {want!r}"
            return True, "last entry matches"
        return False, "no readable entry"


class SqliteProbe(Probe):
    """Watches a SQLite database for writes.

    Built for freebuff, which keeps a WAL-mode db inside the project: the
    -wal file's mtime moves on every write.
    """

    kind = "sqlite"

    def __init__(self, path, quiet_ms=2500, watch="wal_mtime", table="",
                 name=""):
        super().__init__(quiet_ms, name)
        self.path = path or ""
        self.watch = watch or "wal_mtime"
        self.table = table or ""

    def _read(self):
        path = os.path.expanduser(os.path.expandvars(self.path))
        if self.watch == "wal_mtime":
            stats = []
            for candidate in (path + "-wal", path):
                if os.path.isfile(candidate):
                    st = os.stat(candidate)
                    stats.append((os.path.basename(candidate),
                                  st.st_size, round(st.st_mtime, 3)))
            return tuple(stats) or None

        if self.watch == "max_rowid":
            if not self.table or not os.path.isfile(path):
                return None
            import sqlite3
            # read-only, and never block the app that owns the file
            uri = f"file:{path}?mode=ro&immutable=0"
            with sqlite3.connect(uri, uri=True, timeout=0.5) as conn:
                row = conn.execute(
                    f"SELECT COALESCE(MAX(rowid), 0) FROM {self.table}").fetchone()
            return ("rowid", row[0] if row else 0)

        return None


class _OptionalProbe(Probe):
    """A probe whose dependency is not installed.

    Reports UNSUPPORTED rather than pretending. Degrading to "idle" would
    make a missing package look like a finished agent, which is the one
    failure this design must not have.
    """

    def __init__(self, kind, missing, name=""):
        super().__init__(0, name or kind)
        self.kind = kind
        self.missing = missing

    def _read(self):
        return None

    def poll(self, now):
        self.reason = f"{self.kind}: needs {self.missing}, which is not installed"
        return UNSUPPORTED, self.reason


def window_probe(title_match="", idle_pattern="", busy_pattern="", **kw):
    """UI Automation text probe, when the dependency exists."""
    try:
        import uiautomation  # noqa: F401
    except ImportError:
        return _OptionalProbe("window", "uiautomation")
    return _OptionalProbe("window", "uiautomation")   # reader not built yet


def process_probe(cpu_below=5.0, **kw):
    """CPU-idle probe, when psutil exists."""
    try:
        import psutil  # noqa: F401
    except ImportError:
        return _OptionalProbe("process", "psutil")
    return _OptionalProbe("process", "psutil")        # reader not built yet


def build(spec, project=None):
    """One probe from a config entry. Unknown kinds are unsupported."""
    if not isinstance(spec, dict):
        return _OptionalProbe("unknown", "a valid config entry")
    kind = spec.get("kind")
    quiet = spec.get("quiet_ms", 2000)

    if kind == "file":
        pattern = (spec.get("glob") or "").replace("{project}", project or "")
        return FileProbe(pattern, quiet_ms=quiet,
                         newest=spec.get("newest", True),
                         last_line_json=spec.get("last_line_json"),
                         ignore_types=spec.get("ignore_types", ()))
    if kind == "sqlite":
        path = (spec.get("path") or "").replace("{project}", project or "")
        return SqliteProbe(path, quiet_ms=quiet,
                           watch=spec.get("watch", "wal_mtime"),
                           table=spec.get("table", ""))
    if kind == "window":
        return window_probe(**{k: v for k, v in spec.items() if k != "kind"})
    if kind == "process":
        return process_probe(**{k: v for k, v in spec.items() if k != "kind"})
    return _OptionalProbe(str(kind), "a known probe kind")


def combine(probes, now):
    """(all idle?, [reasons]) — the engine's single question.

    An empty probe list is BUSY, not idle: an adapter that describes no
    signal knows nothing about the agent, and "knows nothing" must never be
    the thing that lets a prompt out.
    """
    reasons = []
    if not probes:
        return False, ["no probes configured"]
    all_idle = True
    for probe in probes:
        state, reason = probe.poll(now)
        reasons.append(reason)
        if state != IDLE:
            all_idle = False
    return all_idle, reasons
