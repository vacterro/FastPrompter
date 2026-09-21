"""T-1300: the session-wide smoke sound mute owns its replacements.

The release gate runs ``pytest tests/ tests_smoke/`` in ONE process. The smoke
conftest replaces two process-global sound exits (``SoundManager._play_winsound``
and ``sound_manager.QSoundEffect``) for the whole session; this regression
proves the originals are captured BEFORE the replacement and the EXACT objects
come back, so the mute cannot outlive the smoke tests and leak into any suite
that runs after them. Runs in a clean subprocess so "before the fixture" is
observable instead of assumed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = '''
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.getcwd()
for sub in ("src", "tests", "tests_smoke"):
    sys.path.insert(0, os.path.join(root, sub))

from fastprompter.core import sound_manager as sm
from fastprompter.core.sound_manager import SoundManager
import _smoke_support as harness

before = (vars(SoundManager).get("_play_winsound"), getattr(sm, "QSoundEffect", None))
harness.mute_sound_at_device()
inside = (vars(SoundManager).get("_play_winsound"), getattr(sm, "QSoundEffect", None))
harness.restore_sound_at_device()
after = (vars(SoundManager).get("_play_winsound"), getattr(sm, "QSoundEffect", None))

assert inside[0] is not before[0], "play_winsound not replaced inside the mute"
assert inside[1] is not before[1], "QSoundEffect not replaced inside the mute"
assert after[0] is before[0], "play_winsound identity not restored"
assert after[1] is before[1], "QSoundEffect identity not restored"

# idempotent and safe: restore without a prior mute changes nothing
harness.restore_sound_at_device()
assert (vars(SoundManager).get("_play_winsound"), getattr(sm, "QSoundEffect", None)) == before
print("SOUND_OWNERSHIP_OK")
'''


def test_sound_mute_ownership_is_exact():
    done = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        timeout=300,
    )
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "SOUND_OWNERSHIP_OK" in done.stdout, (done.stdout, done.stderr)
