"""Build the portable FastPrompter.exe with an explicit, recorded toolchain.

Usage:
    python tools/build.py [--upx on|off] [--expected-nuitka VERSION] [--allow-any-toolchain]

Determinism contract (0.8.68 release hardening):

- Nuitka is NEVER auto-installed; install the locked build environment with
  ``uv sync --group dev --extra build`` and re-run.
- The Nuitka version must equal the accepted pin (default 4.2.1); a different
  compiler refuses unless ``--allow-any-toolchain`` is passed and the override
  is recorded in the build report.
- UPX is OFF by default and only used when explicitly requested with
  ``--upx on`` (or FASTPROMPTER_UPX=on) AND present; the presence of an
  unrelated PATH executable never changes the release binary silently.

After a successful build, build/build_report.json records Python, Nuitka,
PyQt6, UPX policy/version, platform, and the EXE identity for the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_NUITKA_PIN = "4.2.1"
REPORT_PATH = Path(__file__).resolve().parents[1] / "build" / "build_report.json"


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _require_nuitka(pin: str, allow_any: bool) -> str:
    if importlib.util.find_spec("nuitka") is None:
        raise SystemExit(
            "Nuitka is not installed in this environment. The build toolchain is "
            "explicit: run `uv sync --group dev --extra build` (Nuitka "
            f"{pin}) and re-run tools/build.py. Auto-install is disabled."
        )
    installed = _version("nuitka")
    if installed != pin and not allow_any:
        raise SystemExit(
            f"Nuitka {installed or 'unknown'} != accepted pin {pin}. "
            "Use the locked environment, or pass --allow-any-toolchain to "
            "override (recorded in the build report)."
        )
    return installed


def _upx_settings(mode: str) -> tuple[str, str]:
    if mode not in ("on", "off"):
        raise SystemExit(f"invalid UPX policy {mode!r}; expected on|off")
    if mode == "off":
        return "off", ""
    upx_bin = shutil.which("upx")
    if not upx_bin:
        raise SystemExit("UPX policy is ON but no upx executable was found in PATH")
    try:
        out = subprocess.run([upx_bin, "--version"], capture_output=True, text=True, timeout=20)
        first_line = (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else "upx"
    except (OSError, subprocess.SubprocessError):
        first_line = "upx (version unreadable)"
    return "on", first_line


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_report(payload: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_PATH.with_name(REPORT_PATH.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, REPORT_PATH)


def build_with_nuitka(upx_mode: str, pin: str, allow_any: bool) -> int:
    project_root = Path(__file__).resolve().parents[1]
    nuitka_version = _require_nuitka(pin, allow_any)
    env_upx = os.environ.get("FASTPROMPTER_UPX", "").strip().lower()
    if env_upx and upx_mode == "off":
        upx_mode = env_upx
    upx_policy, upx_version = _upx_settings(upx_mode)

    print(f"Toolchain: Python {platform.python_version()}, Nuitka {nuitka_version}, "
          f"PyQt6 {_version('PyQt6') or 'unknown'}, UPX {upx_policy}")
    print("Starting Nuitka build for FastPrompter...")

    cmd = [sys.executable, "-m", "nuitka",
           "--include-package-data=tzdata", "FastPrompter.pyw"]
    if upx_policy == "on":
        cmd.append("--plugin-enable=upx")
        cmd.append(f"--upx-binary={shutil.which('upx')}")

    print("Running:", " ".join(cmd))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root / "src") + os.pathsep + env.get("PYTHONPATH", "")

    try:
        subprocess.run(cmd, check=True, env=env, cwd=str(project_root))
    except subprocess.CalledProcessError as exc:
        print(f"\n[ERROR] Build failed with exit code {exc.returncode}")
        return exc.returncode

    exe = project_root / "build" / "FastPrompter.exe"
    exe_info = {}
    if exe.is_file():
        exe_info = {
            "path": "build/FastPrompter.exe",
            "size": exe.stat().st_size,
            "sha256": _sha256(exe),
        }
        print(f"\n[SUCCESS] Build complete: FastPrompter.exe "
              f"({exe_info['size'] / 1048576:.1f} MB, sha256 {exe_info['sha256'][:16]}...)")

    report = {
        "schema_version": 1,
        "operation": "build_report",
        "recorded_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "result": "BUILD_EXIT 0",
        "toolchain": {
            "python": platform.python_version(),
            "nuitka": nuitka_version,
            "nuitka_pin": pin,
            "nuitka_pin_enforced": not allow_any,
            "pyqt6": _version("PyQt6"),
            "upx_policy": upx_policy,
            "upx_version": upx_version,
            "platform": platform.platform(),
        },
        "exe": exe_info,
    }
    _write_report(report)
    print(f"Build report: {REPORT_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upx", choices=("on", "off"), default="off")
    parser.add_argument("--expected-nuitka", default=DEFAULT_NUITKA_PIN)
    parser.add_argument("--allow-any-toolchain", action="store_true")
    args = parser.parse_args(argv)
    return build_with_nuitka(args.upx, args.expected_nuitka, args.allow_any_toolchain)


if __name__ == "__main__":
    sys.exit(main())
