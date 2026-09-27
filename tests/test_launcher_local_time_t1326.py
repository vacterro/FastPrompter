from __future__ import annotations

import ctypes
import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "FastPrompter.pyw"


class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("year", ctypes.c_ushort), ("month", ctypes.c_ushort),
        ("weekday", ctypes.c_ushort), ("day", ctypes.c_ushort),
        ("hour", ctypes.c_ushort), ("minute", ctypes.c_ushort),
        ("second", ctypes.c_ushort), ("milliseconds", ctypes.c_ushort),
    ]


def _windows_local_now() -> datetime.datetime:
    value = _SYSTEMTIME()
    assert ctypes.windll.kernel32.GetLocalTime(ctypes.byref(value))
    return datetime.datetime(
        value.year, value.month, value.day,
        value.hour, value.minute, value.second, value.milliseconds * 1000,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows local-time contract")
def test_launcher_ignores_an_inherited_utc_timezone():
    expected = _windows_local_now()
    code = (
        "import datetime, os, runpy; "
        "assert os.environ['TZ'] == 'UTC'; "
        f"runpy.run_path({str(LAUNCHER)!r}, run_name='fastprompter_launcher_test'); "
        "print(datetime.datetime.now().isoformat(timespec='seconds'))"
    )
    env = dict(os.environ, TZ="UTC")
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        text=True, capture_output=True, timeout=15, check=True)
    shown = datetime.datetime.fromisoformat(result.stdout.strip())
    assert abs((shown - expected).total_seconds()) < 5
