"""Claude quota straight from ``claude -p "/usage"`` — the authoritative source.

Claude Code's own ``/usage`` answer is the only local source that carries BOTH
the percentage and the reset time for every window, and it comes from
Anthropic's ``/api/oauth/usage`` endpoint rather than from a file whose meaning
FastPrompter had to guess. In print mode the command is answered locally by the
CLI: measured on 2.1.259 it reports ``num_turns: 0`` and ``total_cost_usd: 0``,
so reading the quota never spends any.

The text it prints (verbatim, 2.1.259)::

    You are currently using your subscription to power your Claude Code usage

    Current session: 65% used · resets Sep 3, 4:49pm (Europe/Tallinn)
    Current week (all models): 64% used · resets Sep 8, 4:59pm (Europe/Tallinn)

The timestamp names its IANA zone. ``zoneinfo`` interprets that vendor rule so
an SSH host, travel, or a differently configured workstation cannot shift the
instant. Older output without a zone keeps the machine-local fallback. The year
is present only when it differs from the current one; an omitted calendar date
already earlier than today therefore belongs to next year, while a same-day
elapsed minute stays elapsed instead of jumping forward a year.

Nothing is inferred: a line that does not parse is dropped rather than guessed
at, and a missing ``/usage`` answer leaves the caller with no window at all.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastprompter.core.usage_limits.cli_tools import resolve_binary, run_cli

# "Current session: 65% used · resets Sep 3, 4:49pm (Europe/Tallinn)"
_LINE_RE = re.compile(
    r"^(?P<title>[^:]+):\s*(?P<pct>\d{1,3})%\s*used"
    r"(?:\s*[·\u00b7-]\s*resets\s*(?P<when>[^(\n]+?)\s*(?:\((?P<tz>[^)]*)\))?)?\s*$")

# "Sep 3, 4:49pm" / "Sep 8, 5pm" / "Sep 3, 2027, 4:49pm"
_WHEN_RE = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})"
    r"(?:,\s*(?P<year>\d{4}))?"
    r",\s*(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]m)$",
    re.I)

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# Claude Code's own limit names -> provider-neutral window keys (model.py).
_TITLES = {
    "current session": "five_hour",
    "current week (all models)": "weekly",
    "spend limit": "spend_limit",
}
# "Current week (Sonnet)" is a per-model weekly pool; it is a real independent
# limit, so it keeps its own key instead of overwriting the all-models weekly.
_SCOPED_WEEKLY_RE = re.compile(r"^current week \((?P<scope>.+)\)$")


def parse_reset(text: str, now: float | None = None,
                 tz_name: str | None = None) -> float | None:
    """CLI wall time plus its named zone -> epoch seconds."""
    match = _WHEN_RE.match((text or "").strip())
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    hour = int(match.group("hour")) % 12
    if match.group("ampm").lower() == "pm":
        hour += 12
    day = int(match.group("day"))
    reference_epoch = time.time() if now is None else now
    zone = None
    if tz_name:
        try:
            zone = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    reference = datetime.datetime.fromtimestamp(reference_epoch, tz=zone)
    explicit_year = match.group("year")
    year = int(explicit_year or reference.year)
    try:
        moment = datetime.datetime(year, month, day, hour,
                                   int(match.group("minute") or 0), tzinfo=zone)
    except ValueError:
        return None
    if (explicit_year is None
            and (month, day) < (reference.month, reference.day)):
        try:
            moment = moment.replace(year=moment.year + 1)
        except ValueError:
            moment = moment.replace(year=moment.year + 1, day=28)
    return moment.timestamp()


def parse_usage_text(text: str, now: float | None = None) -> dict:
    """``{window_key: {"used": pct, "resets_at": epoch|None}}`` from /usage."""
    windows: dict[str, dict] = {}
    for raw_line in (text or "").splitlines():
        match = _LINE_RE.match(raw_line.strip())
        if match is None:
            continue
        title = " ".join(match.group("title").split()).lower()
        key = _TITLES.get(title)
        if key is None:
            scoped = _SCOPED_WEEKLY_RE.match(title)
            if scoped is None:
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", scoped.group("scope").lower())
            key = f"weekly_{slug.strip('_')}" or "weekly"
        used = max(0.0, min(100.0, float(match.group("pct"))))
        windows[key] = {
            "used": used,
            "resets_at": parse_reset(
                match.group("when") or "", now=now,
                tz_name=match.group("tz")),
        }
    return windows


def _probe_dir() -> str:
    """A stable, FastPrompter-owned cwd for the probe.

    ``claude`` files its transcript under a slug derived from the working
    directory, so probing from a fixed scratch directory keeps every artefact in
    ONE predictable place instead of scattering one project entry per directory
    the app happened to be started from.
    """
    path = Path(tempfile.gettempdir()) / "fastprompter-limit-probe"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return tempfile.gettempdir()
    return str(path)


def _project_slug(directory: str) -> str:
    """Claude Code's own transcript-directory name for a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(directory))


def _drop_transcript(session_id: str, directory: str,
                     config_dir: str = "") -> None:
    """Delete the transcript this probe just created.

    A quota read is not a conversation. Left alone, a 3-minute sweep would file
    a new 5 KB transcript every sweep forever — and those same transcripts are
    what the refusal scanner reads, so the junk would also slow that down.

    ``config_dir`` is the account's own ``CLAUDE_CONFIG_DIR``; the CLI files the
    transcript under THAT root, so a second account's probe litter is only
    reachable through it. Empty means the default ``~/.claude``.
    """
    if config_dir:
        root = Path(config_dir)
    else:
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
        if not home:
            return
        root = Path(home) / ".claude"
    path = root / "projects" / _project_slug(directory) / f"{session_id}.jsonl"
    try:
        path.unlink()
    except OSError:
        pass


def read_usage(deadline: float, *, binary: str = "",
               now: float | None = None, config_dir: str = "") -> dict:
    """Run ``claude -p "/usage"`` and return the parsed windows.

    Returns ``{"windows": {...}, "captured_at": epoch, "source": str}`` or
    ``{"error": (code, summary)}``. Never raises.

    ``config_dir`` selects WHICH logged-in account answers. The CLI resolves its
    whole identity — credentials, settings, transcripts — from
    ``CLAUDE_CONFIG_DIR``, so a second account is read by pointing the child at
    its own home rather than by any switching command. Empty keeps the ambient
    environment, which is the default ``~/.claude`` account.
    """
    executable = binary or resolve_binary("claude")
    if not executable:
        return {"error": ("cli_not_installed",
                          "Claude Code CLI not found on PATH")}
    session_id = str(uuid.uuid4())
    directory = _probe_dir()
    env = None
    if config_dir:
        # Copied, never mutated in place: the parent process is FastPrompter
        # itself and other probes read os.environ concurrently.
        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = config_dir
    result = run_cli(
        [executable, "-p", "/usage", "--output-format", "json",
         "--session-id", session_id],
        deadline, cwd=directory, env=env)
    _drop_transcript(session_id, directory, config_dir)
    if not result["ok"]:
        return {"error": ("cli_failed", f"claude /usage: {result['error']}")}
    try:
        payload = json.loads(result["stdout"])
    except (ValueError, TypeError):
        return {"error": ("cli_bad_output",
                          "claude /usage did not return JSON")}
    if not isinstance(payload, dict) or payload.get("is_error"):
        return {"error": ("cli_failed", "claude /usage reported an error")}
    answer = payload.get("result")
    if not isinstance(answer, str) or not answer.strip():
        return {"error": ("cli_bad_output", "claude /usage returned no text")}
    windows = parse_usage_text(answer, now=now)
    if not windows:
        # Not a fault: an API-key (non-subscription) account has no plan quota,
        # and the CLI answers with the cost summary instead.
        return {"error": ("cli_no_limits",
                          "claude /usage reported no subscription limits")}
    return {
        "windows": windows,
        "captured_at": time.time() if now is None else now,
        "source": "claude-cli-usage",
        # The full first-party envelope, so the provider's defensive
        # campaign scan (T-1360) can see vendor metadata beyond the parsed
        # windows without this module guessing at schemas.
        "raw": payload,
    }
