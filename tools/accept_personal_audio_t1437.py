"""T-1437 / SRC-134 section 9: P0 acceptance against the REAL operator settings.

The live database is read from a COPY taken with the SQLite online backup API
(never a raw file copy of a WAL database) and opened read-only, so this script
can never modify the operator's installation (R19). It prints the exact table
SRC-134 section 9 asks for, then exits non-zero if any selected sound resolves
to nothing or to a packaged synthetic while a personal original exists.

Run: python tools/accept_personal_audio_t1437.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastprompter.core import sound_library as sl  # noqa: E402
from fastprompter.utils.paths import get_data_dir  # noqa: E402


def _snapshot(src: Path, dst: Path) -> None:
    """Consistent copy of a live SQLite database (WAL included)."""
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(dst.as_posix())
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _refs_from(settings: dict[str, str]) -> list[tuple[str, str]]:
    """(surface, stored_ref) pairs for every sound the operator selected."""
    found: list[tuple[str, str]] = []

    def scan(surface: str, value) -> None:
        if isinstance(value, str):
            text = value.strip()
            if not text.lower().endswith((".wav", ".mp3")):
                return
            found.append((surface, text))
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and item.strip().lower().endswith(
                        (".wav", ".mp3")):
                    found.append((surface, item.strip()))
                else:
                    scan(surface, item)
        elif isinstance(value, list):
            for item in value:
                scan(surface, item)

    for key, raw in settings.items():
        lowered = key.lower()
        if not any(t in lowered for t in ("sound", "audio", "ambien", "timer")):
            continue
        try:
            scan(key, json.loads(raw))
        except (ValueError, TypeError):
            scan(key, raw)
    return found


def _classify(path: str | None) -> str:
    if path is None:
        return "MISSING"
    packaged = os.path.normcase(sl.packaged_root())
    if os.path.normcase(path).startswith(packaged):
        return "PACKAGED"
    return "PERSONAL"


def main() -> int:
    data_dir = Path(get_data_dir())
    live = data_dir / "local_data_v15.db"
    audio = data_dir / "audio.db"
    if not live.is_file():
        print(f"NO_LIVE_DATABASE {live}")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "settings.db"
        _snapshot(live, copy)
        con = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
        try:
            settings = {k: v for k, v in con.execute(
                "SELECT key, value FROM settings")}
        finally:
            con.close()

        rows: list[tuple[str, str, str | None, str]] = []
        for surface, ref in _refs_from(settings):
            bare = ref[5:] if ref.startswith("file:") else ref
            resolved = sl.resolve_sound_ref(bare)
            rows.append((surface, ref, resolved, _classify(resolved)))

        # Ambience lives in audio.db.
        ambience: list[tuple[str, str, str | None, str]] = []
        if audio.is_file():
            amb_copy = Path(tmp) / "audio.db"
            _snapshot(audio, amb_copy)
            con = sqlite3.connect(f"file:{amb_copy.as_posix()}?mode=ro", uri=True)
            try:
                for _id, payload in con.execute(
                        "SELECT id, payload FROM ambience_rules_v1"):
                    rule = json.loads(payload)
                    ref = rule.get("sound_ref") or ""
                    if not ref:
                        continue
                    resolved = sl.resolve_sound_ref(ref)
                    ambience.append((f"ambience:{rule.get('name', _id)}", ref,
                                     resolved, _classify(resolved)))
            finally:
                con.close()

    print("SURFACE|STORED_REF|RESOLVED|CLASS")
    for row in rows + ambience:
        surface, ref, resolved, kind = row
        print(f"{surface}|{ref}|{resolved or ''}|{kind}")

    personal = sum(1 for r in rows + ambience if r[3] == "PERSONAL")
    packaged = sum(1 for r in rows + ambience if r[3] == "PACKAGED")
    missing = sum(1 for r in rows + ambience if r[3] == "MISSING")
    print()
    print(f"PERSONAL_AUDIO_ENABLED {sl.personal_audio_enabled()}")
    print(f"TOTAL {len(rows) + len(ambience)}")
    print(f"RESOLVED_PERSONAL {personal}")
    print(f"RESOLVED_PACKAGED {packaged}")
    print(f"MISSING {missing}")

    if missing:
        print("VERDICT FAIL -- a stored selection resolves to nothing")
        return 1
    if packaged:
        print("VERDICT FAIL -- a stored selection plays a packaged synthetic")
        return 1
    print("VERDICT PASS -- every stored selection plays personal audio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
