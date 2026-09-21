"""Shared helpers for probing agent CLIs, and the one-click installers.

Three vendors ship a CLI that can state its own quota without spending any:

* ``claude -p "/usage"`` — Claude Code, text answer, 0 turns / $0.00;
* ``agy -p "/usage" --output-format json`` — Antigravity CLI, structured;
* ``codex`` — already probed over its app-server JSON-RPC (see _codex_probe).

A CLI is the most reliable source there is: it authenticates the way the vendor
intends, and the number comes from the vendor's own server rather than from a
file FastPrompter guessed the meaning of. This module is only the plumbing —
locating the executable, running it under a hard deadline without a console
flash, and describing how the user can install one.

Nothing here ever runs an installer on its own. ``INSTALLERS`` is data: the exact
command, where it lands, and who publishes it. The UI shows that command and only
runs it after the user explicitly confirms, because piping a remote script into
a shell is exactly the kind of action that must never be implicit.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import time
from pathlib import Path

# CREATE_NO_WINDOW: a 3-minute quota sweep must not flash a console window.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
# BELOW_NORMAL_PRIORITY_CLASS: probe child processes must never starve the GUI thread.
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000 if os.name == "nt" else 0
# STARTF_FORCEOFFFEEDBACK: prevent Windows from showing the spinning hourglass cursor.
_STARTF_FORCEOFFFEEDBACK = 0x00000040 if os.name == "nt" else 0
_STARTF_USESHOWWINDOW = 0x00000001 if os.name == "nt" else 0
_SW_HIDE = 0
_CREATE_SUSPENDED = 0x00000004 if os.name == "nt" else 0
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_BASIC_LIMIT_INFORMATION = 2


def silent_startupinfo() -> subprocess.STARTUPINFO | None:
    """STARTUPINFO suppressing console windows and the Windows spinning feedback cursor."""
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= _STARTF_USESHOWWINDOW | _STARTF_FORCEOFFFEEDBACK
    si.wShowWindow = _SW_HIDE
    return si


def silent_creationflags() -> int:
    """Creation flags: no console window, below-normal priority so UI never hitches."""
    return _NO_WINDOW | _BELOW_NORMAL_PRIORITY_CLASS


@dataclasses.dataclass(frozen=True)
class CliTool:
    """One agent CLI: how to find it, and how the user installs it."""

    key: str                  # provider_id it feeds
    binary: str               # executable stem, resolved on PATH
    label: str                # human name for the UI
    # Where the official installer puts it, checked when PATH has not been
    # refreshed yet (a freshly installed CLI is invisible to an app that
    # started before the installer edited PATH).
    fallback_paths: tuple[str, ...] = ()
    install_command: str = ""     # verbatim, shown to the user before running
    install_source: str = ""      # who publishes it, so the user can judge
    install_target: str = ""      # where the binary lands


INSTALLERS = (
    CliTool(
        key="claude",
        binary="claude",
        label="Claude Code CLI",
        fallback_paths=("~/.local/bin/claude.exe", "~/.local/bin/claude"),
        install_command="irm https://claude.ai/install.ps1 | iex",
        install_source="claude.ai (Anthropic)",
        install_target="%USERPROFILE%\\.local\\bin\\claude.exe",
    ),
    CliTool(
        key="antigravity",
        binary="agy",
        label="Antigravity CLI",
        fallback_paths=("~/AppData/Local/agy/bin/agy.exe",
                        "~/.local/bin/agy.exe",
                        "%ProgramFiles%/Google/antigravity-cli/agy.exe",
                        "~/.local/bin/agy"),
        install_command="irm https://antigravity.google/cli/install.ps1 | iex",
        install_source="antigravity.google (Google)",
        install_target="%LOCALAPPDATA%\\agy\\bin\\agy.exe",
    ),
    CliTool(
        key="codex",
        binary="codex",
        label="Codex CLI",
        fallback_paths=("~/.local/bin/codex.exe", "~/.local/bin/codex",
                        "~/AppData/Roaming/npm/codex.cmd"),
        install_command="irm https://chatgpt.com/codex/install.ps1 | iex",
        install_source="chatgpt.com/codex (OpenAI)",
        install_target="on PATH (installer-chosen directory)",
    ),
)

INSTALLERS_BY_KEY = {tool.key: tool for tool in INSTALLERS}


def resolve_binary(tool: CliTool | str) -> str:
    """Absolute path to the CLI, or ``""``.

    PATH first, then the installer's own directory: the CLI a user installs
    while FastPrompter is running is NOT on this process's PATH (Windows hands
    every process a PATH snapshot at launch), so a PATH-only lookup would
    report "not installed" until the app restarts.
    """
    if isinstance(tool, str):
        tool = INSTALLERS_BY_KEY.get(tool) or CliTool(key=tool, binary=tool,
                                                      label=tool)
    # Legacy IDE aliases also use "agy". The official CLI install location
    # must win, otherwise Connect can open the editor in our repository.
    if tool.key == "antigravity":
        for candidate in tool.fallback_paths:
            path = Path(os.path.expandvars(os.path.expanduser(candidate)))
            if path.is_file():
                return str(path)
    found = shutil.which(tool.binary)
    if found:
        if tool.key == "antigravity" and Path(found).suffix.lower() in (".cmd", ".bat"):
            # The IDE's old agy launcher accepts a folder, not /usage.
            # Official Windows CLI distributions provide agy.exe.
            return ""
        return found
    for candidate in tool.fallback_paths:
        path = Path(os.path.expanduser(candidate))
        if path.is_file():
            return str(path)
    return ""


def _guarded_windows_process(argv: list[str], timeout: float, *,
                             cwd: str | None, env: dict | None) -> dict:
    """Run one process while Windows forbids it from spawning children.

    Antigravity launches ``rundll32`` when authentication expires.  Environment
    hints are not an enforcement boundary, so its background quota probe runs
    suspended, is placed in an ActiveProcessLimit=1 Job Object, and is resumed
    only after that kernel policy is active.  If any guard step fails, the
    suspended process is killed and no uncontained probe is allowed to run.
    """
    import ctypes
    from ctypes import wintypes

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    # Explicit signatures: without argtypes, ctypes passes HANDLEs as 32-bit
    # ints and silently truncates 64-bit handle values, failing the call.
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = ctypes.c_long
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    def _guard_failed() -> dict:
        """Guard-step failure, with the Windows error code when available."""
        code = ctypes.get_last_error()
        detail = f" (WinError {code})" if code else ""
        return {"ok": False, "stdout": "",
                "error": f"browser_guard_failed{detail}"}

    def _kill(proc: subprocess.Popen) -> None:
        """Terminate a possibly-suspended process and release its pipes."""
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return _guard_failed()

    process = None
    try:
        limits = _JOBOBJECT_BASIC_LIMIT_INFORMATION()
        limits.LimitFlags = _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        limits.ActiveProcessLimit = 1
        if not kernel32.SetInformationJobObject(
                job, _JOB_OBJECT_BASIC_LIMIT_INFORMATION,
                ctypes.byref(limits), ctypes.sizeof(limits)):
            return _guard_failed()

        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            creationflags=silent_creationflags() | _CREATE_SUSPENDED,
            startupinfo=silent_startupinfo(),
            stdin=subprocess.DEVNULL,
        )
        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            failure = _guard_failed()   # capture WinError before killing
            _kill(process)
            return failure
        if ntdll.NtResumeProcess(int(process._handle)) != 0:
            failure = _guard_failed()
            _kill(process)
            return failure
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
            detail = (stderr or "").strip().splitlines()
            return {"ok": False, "stdout": stdout or "",
                    "error": (detail[0][:160] if detail else "timeout")}
        if process.returncode != 0:
            detail = (stderr or "").strip().splitlines()
            return {"ok": False, "stdout": stdout or "",
                    "error": (detail[0][:160] if detail else
                              f"exit {process.returncode}")}
        return {"ok": True, "stdout": stdout or "", "error": ""}
    except OSError as exc:
        if process is not None:
            _kill(process)
        return {"ok": False, "stdout": "",
                "error": (str(exc) or type(exc).__name__)[:160]}
    finally:
        kernel32.CloseHandle(job)


def run_cli(argv: list[str], deadline: float, *, cwd: str | None = None,
            env: dict | None = None,
            block_child_processes: bool = False) -> dict:
    """Run a CLI under an absolute ``time.monotonic()`` deadline.

    Returns ``{"ok", "stdout", "error"}``. Never raises, never blocks past the
    deadline, never uses a shell (so no argument can be reinterpreted), and
    never opens a console window. A timeout kills the child.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0.1:
        return {"ok": False, "stdout": "", "error": "deadline_exceeded"}
    timeout = min(remaining, 30.0)
    if block_child_processes:
        if os.name != "nt":
            return {"ok": False, "stdout": "",
                    "error": "browser_guard_unavailable"}
        return _guarded_windows_process(
            argv, timeout, cwd=cwd, env=env)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=cwd,
            env=env, creationflags=silent_creationflags(),
            startupinfo=silent_startupinfo(), check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        # ``TimeoutExpired`` keeps output already emitted by the child.  It is
        # especially important for authentication failures: some CLIs print a
        # login/code prompt and then wait, so throwing the partial output away
        # turns a precise "sign in again" state into a useless generic timeout.
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        detail = str(stderr).strip().splitlines()
        return {"ok": False, "stdout": str(stdout),
                "error": (detail[0][:160] if detail else "timeout")}
    except OSError as exc:
        return {"ok": False, "stdout": "", "error": f"{type(exc).__name__}"}
    if result.returncode != 0:
        # stderr can carry an auth hint ("Not logged in"); it is a vendor
        # message about the user's own account, never a credential.
        detail = (result.stderr or "").strip().splitlines()
        return {"ok": False, "stdout": result.stdout or "",
                "error": (detail[0][:160] if detail else
                          f"exit {result.returncode}")}
    return {"ok": True, "stdout": result.stdout or "", "error": ""}


def install_status(key: str) -> dict:
    """Whether one CLI is installed, and what installing it would run."""
    tool = INSTALLERS_BY_KEY.get(key)
    if tool is None:
        return {"key": key, "known": False, "installed": False}
    path = resolve_binary(tool)
    return {
        "key": key,
        "known": True,
        "label": tool.label,
        "installed": bool(path),
        "path": path,
        "command": tool.install_command,
        "source": tool.install_source,
        "target": tool.install_target,
    }


def launch_installer(key: str) -> None:
    """Start one vendor's official installer in its own visible console.

    Deliberately VISIBLE and detached, unlike every other subprocess here:

    * the user must be able to watch a remote script run and answer anything it
      asks — hiding that would be the wrong kind of convenience;
    * an installer takes minutes, so waiting for it would freeze the GUI;
    * the command is the vendor's published one-liner, passed to PowerShell
      verbatim rather than assembled from user input.

    Raises on a failure to START (missing shell, refused spawn); whatever the
    installer itself then reports is the user's to read in that window.
    """
    tool = INSTALLERS_BY_KEY.get(key)
    if tool is None or not tool.install_command:
        raise ValueError(f"no installer is defined for {key!r}")
    if os.name != "nt":
        raise RuntimeError(
            "one-click CLI install is Windows-only; run this in a terminal:\n"
            f"{tool.install_command}")
    shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    # -NoExit keeps the window open on success too, so the user can read what
    # the installer said instead of watching it vanish.
    subprocess.Popen(
        [shell, "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", tool.install_command],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        close_fds=True,
    )


LOGIN_SUBCOMMANDS = {
    "codex": "login",
    "claude": "login",
    "antigravity": "",
}


def launch_login(key: str) -> None:
    """Start one vendor's login workflow in a visible console.

    Visible and detached, like launch_installer: the user must be able to
    complete interactive web authentication, browser SSO, or OAuth code entry.
    """
    tool = INSTALLERS_BY_KEY.get(key)
    binary_path = resolve_binary(key)
    if not binary_path:
        label = tool.label if tool else key
        raise ValueError(f"{label} is not installed yet")
    subcmd = LOGIN_SUBCOMMANDS.get(key, "login")
    if os.name != "nt":
        arg = f" {subcmd}" if subcmd else ""
        raise RuntimeError(
            f"one-click login is Windows-only; run '{tool.binary if tool else key}{arg}' in a terminal"
        )
    shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    if key == "antigravity":
        banner = (
            "Write-Host '=========================================' -ForegroundColor Cyan; "
            "Write-Host ' Antigravity CLI Login' -ForegroundColor Cyan; "
            "Write-Host '=========================================' -ForegroundColor Cyan; "
            "$Host.UI.RawUI.WindowTitle = 'FastPrompter - Antigravity sign-in'; "
            "Write-Host 'If already signed in, /usage prints your limits and exits.' -ForegroundColor Yellow; "
            "Write-Host 'Otherwise a browser opens for Google Sign-In.' -ForegroundColor Yellow; "
            "Write-Host 'Copy the authorization code from the browser' -ForegroundColor Yellow; "
            "Write-Host 'and paste it into this window to authenticate.' -ForegroundColor Yellow; "
            "Write-Host ''; "
        )
        cmd = f"{banner}& '{binary_path.replace(chr(39), chr(39) * 2)}' -p '/usage' --output-format json"
    else:
        cmd = f"& '{binary_path.replace(chr(39), chr(39) * 2)}' {subcmd}".strip()
    subprocess.Popen(
        [shell, "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", cmd],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        close_fds=True,
        cwd=str(Path.home()),
    )
