"""Smart Code Runner — interpreter registry (T-1456).

Explicit registry of interpreter adapters. Windows-first coverage.
No shell=True. Argument-vector execution. UTF-8 staging.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RunnerAdapter:
    """How to run one language."""

    key: str                  # registry key
    display: str              # UI label
    exe_name: str             # executable filename
    args_template: tuple[str, ...]  # e.g. ("-NoProfile", "-ExecutionPolicy", "Bypass", "-File")
    cwd_policy: str           # "project" | "script_dir" | "temp"
    encoding: str = "utf-8"
    extensions: tuple[str, ...] = ()
    available_check: Callable[[], bool] | None = None
    unavailable_reason: str | None = None


class RunnerRegistry:
    """Central registry of interpreter adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, RunnerAdapter] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        # PowerShell 5.1 (Windows built-in)
        self.register(RunnerAdapter(
            key="powershell",
            display="PowerShell",
            exe_name="powershell.exe",
            args_template=("-NoProfile", "-File"),
            cwd_policy="script_dir",
            encoding="utf-16-le",  # PS prefers UTF-16 for -File
            extensions=(".ps1",),
        ))
        # PowerShell 7+ (pwsh)
        self.register(RunnerAdapter(
            key="pwsh",
            display="PowerShell 7+",
            exe_name="pwsh.exe",
            args_template=("-NoProfile", "-File"),
            cwd_policy="script_dir",
            encoding="utf-8",
            extensions=(".ps1",),
        ))
        # CMD / Batch
        self.register(RunnerAdapter(
            key="cmd",
            display="CMD / Batch",
            exe_name="cmd.exe",
            args_template=("/c",),
            cwd_policy="script_dir",
            encoding="cp437",  # legacy console codepage
            extensions=(".bat", ".cmd"),
        ))
        # Python
        self.register(RunnerAdapter(
            key="python",
            display="Python",
            exe_name="python.exe",
            args_template=("-u",),  # unbuffered
            cwd_policy="project",
            encoding="utf-8",
            extensions=(".py",),
            available_check=lambda: bool(shutil.which("python")),
        ))
        # Node.js
        self.register(RunnerAdapter(
            key="node",
            display="Node.js",
            exe_name="node.exe",
            args_template=(),
            cwd_policy="script_dir",
            encoding="utf-8",
            extensions=(".js", ".mjs"),
            available_check=lambda: bool(shutil.which("node")),
        ))
        # AutoHotkey v1
        self.register(RunnerAdapter(
            key="ahk",
            display="AutoHotkey v1",
            exe_name="AutoHotkey.exe",
            args_template=(),
            cwd_policy="script_dir",
            encoding="utf-8",
            extensions=(".ahk",),
            available_check=lambda: bool(shutil.which("autohotkey")),
        ))
        # AutoHotkey v2
        self.register(RunnerAdapter(
            key="ahk2",
            display="AutoHotkey v2",
            exe_name="AutoHotkeyA32.exe",
            args_template=(),
            cwd_policy="script_dir",
            encoding="utf-8",
            extensions=(".ahk",),
            available_check=lambda: bool(shutil.which("autohotkeya32")),
        ))
        # VBScript
        self.register(RunnerAdapter(
            key="cscript",
            display="VBScript",
            exe_name="cscript.exe",
            args_template=("//nologo",),
            cwd_policy="script_dir",
            encoding="utf-8",
            extensions=(".vbs",),
        ))
        # Bash / WSL
        self.register(RunnerAdapter(
            key="bash",
            display="Bash (WSL/Git Bash)",
            exe_name="bash.exe",
            args_template=(),
            cwd_policy="script_dir",
            encoding="utf-8",
            extensions=(".sh",),
            available_check=lambda: bool(shutil.which("bash")),
        ))

    def register(self, adapter: RunnerAdapter) -> None:
        self._adapters[adapter.key] = adapter

    def get(self, key: str) -> RunnerAdapter | None:
        return self._adapters.get(key)

    def all(self) -> list[RunnerAdapter]:
        return list(self._adapters.values())

    def resolve(self, key: str) -> tuple[Path, tuple[str, ...]] | None:
        """Return (exe_path, args) or None if unavailable."""
        adapter = self._adapters.get(key)
        if not adapter:
            return None
        exe = shutil.which(adapter.exe_name)
        if not exe:
            return None
        return (Path(exe), adapter.args_template)


# Global instance
REGISTRY = RunnerRegistry()


@dataclass
class StagedScript:
    """A staged temporary script with cleanup."""

    path: Path
    language_key: str
    source: str
    _temp_dir: Path = field(repr=False)

    def __enter__(self) -> StagedScript:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Remove the script file and its temp directory."""
        try:
            if self.path.exists():
                self.path.unlink()
            # Remove temp dir if empty
            if self._temp_dir.exists() and not any(self._temp_dir.iterdir()):
                self._temp_dir.rmdir()
        except Exception:
            pass


def stage_script(
    source: str,
    language_key: str,
    *,
    working_dir: Path | None = None,
) -> StagedScript:
    """Write source to a temp file with correct encoding. Returns StagedScript."""
    adapter = REGISTRY.get(language_key)
    if not adapter:
        raise ValueError(f"No adapter for language: {language_key}")

    ext = adapter.extensions[0] if adapter.extensions else ".txt"
    temp_dir = Path(tempfile.mkdtemp(prefix="fp_run_"))
    script_path = temp_dir / f"script{ext}"
    script_path.write_text(source, encoding=adapter.encoding)
    return StagedScript(
        path=script_path,
        language_key=language_key,
        source=source,
        _temp_dir=temp_dir,
    )


def _default_project_dir() -> Path:
    """Safe fallback working directory."""
    # Use temp dir, not data dir, to avoid sync/backup
    return Path(tempfile.gettempdir()) / "FastPrompter_Projects"


# ---------------------------------------------------------------------------
# QProcess-based async execution (in ui/code_run_dialog.py to avoid Qt import)
# ---------------------------------------------------------------------------
