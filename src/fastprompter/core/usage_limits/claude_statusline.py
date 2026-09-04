"""Claude Code status-line bridge for authoritative usage percentages.

Claude Code sends structured ``rate_limits`` data to a configured status-line
command.  The bridge stores only a tiny sanitized cache (window percentages,
reset times, and capture time), then delegates to the user's original status
line if one existed.  It never stores the full session payload or credentials.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BRIDGE_ARG = "--claude-statusline-bridge"
BRIDGE_MARKER = "fastprompter-claude-limits-v1"
CACHE_NAME = "fastprompter-rate-limits.json"
BRIDGE_CONFIG_NAME = "fastprompter-limit-bridge.json"
MAX_STDIN_BYTES = 4 * 1024 * 1024


class BridgeConfigError(RuntimeError):
    pass


def claude_dir(home: str | os.PathLike | None = None) -> Path:
    if home is not None:
        return Path(home) / ".claude"
    root = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not root:
        raise BridgeConfigError("could not resolve HOME / USERPROFILE")
    return Path(root) / ".claude"


def cache_path_for_dir(directory: str | os.PathLike) -> Path:
    return Path(directory) / CACHE_NAME


def _atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2,
                      sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_json_object(path: Path, *, missing_ok=False) -> dict:
    if missing_ok and not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise BridgeConfigError(f"file not found: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BridgeConfigError(f"expected a JSON object in {path}")
    return value


def _finite_percentage(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(100.0, value))


def _reset_value(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 0 < float(value) < 10**12:
        return float(value)
    if isinstance(value, str):
        # Keep an ISO timestamp as text; the provider parses it without
        # broadening this cache to include any other session information.
        value = value.strip()
        if value and len(value) <= 64:
            return value
    return None


def sanitize_statusline_payload(payload: dict, *, captured_at=None) -> dict | None:
    """Extract only documented quota fields; return None before first data."""
    if not isinstance(payload, dict):
        return None
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return None
    clean = {}
    for key in ("five_hour", "seven_day"):
        bucket = rate_limits.get(key)
        if not isinstance(bucket, dict):
            continue
        used = _finite_percentage(
            bucket.get("used_percentage", bucket.get("usedPercent")))
        if used is None:
            continue
        clean_bucket = {"used_percentage": used}
        reset = _reset_value(bucket.get("resets_at", bucket.get("resetsAt")))
        if reset is not None:
            clean_bucket["resets_at"] = reset
        clean[key] = clean_bucket
    if not clean:
        return None
    return {
        "schema_version": 1,
        "source": "claude-code-statusline",
        "captured_at": float(captured_at if captured_at is not None else time.time()),
        "rate_limits": clean,
    }


def capture_payload(payload: dict, directory: str | os.PathLike | None = None,
                    *, captured_at=None) -> bool:
    clean = sanitize_statusline_payload(payload, captured_at=captured_at)
    if clean is None:
        return False
    target_dir = Path(directory) if directory is not None else claude_dir()
    _atomic_json_write(cache_path_for_dir(target_dir), clean)
    return True


def current_bridge_command() -> str:
    """Command Claude Code can invoke in source and frozen builds."""
    frozen = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    if frozen:
        argv = [str(Path(sys.executable).resolve()), BRIDGE_ARG]
    else:
        launcher = Path(__file__).resolve().parents[4] / "FastPrompter.pyw"
        interpreter = Path(sys.executable)
        if interpreter.name.lower() == "pythonw.exe":
            console_python = interpreter.with_name("python.exe")
            if console_python.exists():
                interpreter = console_python
        argv = [str(interpreter.resolve()), str(launcher), BRIDGE_ARG]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _is_bridge_statusline(value) -> bool:
    return (isinstance(value, dict)
            and value.get("type") == "command"
            and BRIDGE_ARG in str(value.get("command", "")))


def install_bridge(directory: str | os.PathLike | None = None,
                   command: str | None = None) -> dict:
    """Install wrapper, preserving the exact previous statusLine value.

    Re-running this over a STALE bridge (one whose recorded interpreter/launcher
    path no longer exists) is the repair: the sidecar backup is left untouched,
    so the user's original status line still comes back on disconnect, and only
    the command is rewritten to the paths that work now.
    """
    directory = Path(directory) if directory is not None else claude_dir()
    settings_path = directory / "settings.json"
    sidecar_path = directory / BRIDGE_CONFIG_NAME
    settings = _read_json_object(settings_path, missing_ok=True)
    existing = settings.get("statusLine")
    sidecar = _read_json_object(sidecar_path, missing_ok=True)
    if (_is_bridge_statusline(existing)
            and sidecar.get("marker") != BRIDGE_MARKER):
        raise BridgeConfigError(
            "FastPrompter statusLine is present but its restore backup is missing")
    if not _is_bridge_statusline(existing):
        sidecar = {
            "schema_version": 1,
            "marker": BRIDGE_MARKER,
            "had_status_line": "statusLine" in settings,
            "original_status_line": existing,
        }
        _atomic_json_write(sidecar_path, sidecar)
    wrapper = {"type": "command", "command": command or current_bridge_command()}
    if isinstance(existing, dict):
        for key in ("padding", "refreshInterval"):
            if key in existing:
                wrapper[key] = existing[key]
    settings["statusLine"] = wrapper
    _atomic_json_write(settings_path, settings)
    return {"connected": True, "settings_path": str(settings_path),
            "cache_path": str(cache_path_for_dir(directory))}


def uninstall_bridge(directory: str | os.PathLike | None = None) -> dict:
    """Restore the pre-FastPrompter status line without touching later edits."""
    directory = Path(directory) if directory is not None else claude_dir()
    settings_path = directory / "settings.json"
    sidecar_path = directory / BRIDGE_CONFIG_NAME
    settings = _read_json_object(settings_path, missing_ok=True)
    current = settings.get("statusLine")
    if not _is_bridge_statusline(current):
        raise BridgeConfigError(
            "Claude statusLine changed after FastPrompter connected; "
            "refusing to overwrite the newer setting")
    sidecar = _read_json_object(sidecar_path)
    if sidecar.get("marker") != BRIDGE_MARKER:
        raise BridgeConfigError("FastPrompter bridge backup is missing or invalid")
    if sidecar.get("had_status_line"):
        settings["statusLine"] = sidecar.get("original_status_line")
    else:
        settings.pop("statusLine", None)
    _atomic_json_write(settings_path, settings)
    try:
        sidecar_path.unlink()
    except OSError:
        pass
    return {"connected": False, "settings_path": str(settings_path)}


def bridge_status(directory: str | os.PathLike | None = None) -> dict:
    """Whether the status-line bridge is installed, AND still points at us.

    A command containing ``BRIDGE_ARG`` is not enough to call the bridge
    healthy: the command is written with the ABSOLUTE interpreter and launcher
    paths that existed at install time, so moving the checkout, switching from
    source to the frozen EXE, or recreating the venv leaves Claude Code
    faithfully running a path that no longer exists. That fails silently — the
    settings dialog said "connected" while no cache was ever written.

    ``stale`` marks exactly that case, and ``expected_command`` is what a
    reconnect would install.
    """
    directory = Path(directory) if directory is not None else claude_dir()
    settings = _read_json_object(directory / "settings.json", missing_ok=True)
    status_line = settings.get("statusLine")
    connected = _is_bridge_statusline(status_line)
    installed = str(status_line.get("command", "")) if connected else ""
    try:
        expected = current_bridge_command()
    except Exception:
        expected = ""
    cache_path = cache_path_for_dir(directory)
    return {
        "connected": connected,
        "has_cache": cache_path.is_file(),
        "cache_path": str(cache_path),
        "command": installed,
        "expected_command": expected,
        # Compared case-insensitively: Windows hands back drive letters and
        # program-directory names in whatever case the caller used, and a
        # case difference alone still runs the same executable.
        "stale": bool(connected and expected
                      and installed.casefold() != expected.casefold()),
    }


def _forward_original(raw: bytes, directory: Path) -> int:
    try:
        sidecar = _read_json_object(directory / BRIDGE_CONFIG_NAME,
                                    missing_ok=True)
        original = sidecar.get("original_status_line")
        command = original.get("command") if isinstance(original, dict) else None
        if not command or BRIDGE_ARG in str(command):
            return 0
        result = subprocess.run(str(command), input=raw, shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=5,
                                check=False)
        if result.stdout:
            sys.stdout.buffer.write(result.stdout)
            sys.stdout.buffer.flush()
        return int(result.returncode)
    except Exception:
        return 0


def bridge_main() -> int:
    """Status-line subprocess entry point. Always fail quiet for Claude UI."""
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    except Exception:
        raw = b""
    try:
        if len(raw) <= MAX_STDIN_BYTES:
            payload = json.loads(raw.decode("utf-8"))
            capture_payload(payload)
    except Exception:
        pass
    try:
        _forward_original(raw[:MAX_STDIN_BYTES], claude_dir())
    except Exception:
        pass
    # A status-line helper must never trigger FastPrompter's fatal-dialog path
    # merely because capture/delegation failed or the old formatter returned
    # nonzero.
    return 0
