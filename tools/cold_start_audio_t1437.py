"""T-1437 / SRC-134 P0 proof: a cold start does not replace the operator's sounds.

SRC-134's terminal acceptance requires "rebuild/restart does not replace original
sounds". Launching the GUI is not required to answer that: the only thing a
restart does to audio settings is run the startup migration and the ambience
seeding/repair path. This script runs both against a COPY of the operator's real
databases and asserts that nothing was rewritten.

It never opens the live database for writing and never touches the shipped
sound folder. Exit 0 means no ref was rewritten, no ambience rule changed, and
every stored ref still resolves.

Run: python tools/cold_start_audio_t1437.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastprompter.core import ambience_store, sound_manager  # noqa: E402
from fastprompter.core import sound_library as sl  # noqa: E402
from fastprompter.utils.paths import get_data_dir  # noqa: E402


def _snapshot(src: Path, dst: Path) -> None:
    """Consistent copy of a live SQLite database, WAL included."""
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(dst.as_posix())
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def main() -> int:
    data = Path(get_data_dir())
    settings_db = data / "local_data_v15.db"
    audio_db = data / "audio.db"
    if not settings_db.is_file():
        print(f"NO_LIVE_DATABASE {settings_db}")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="coldstart_"))
    try:
        _snapshot(settings_db, tmp / "settings.db")
        con = sqlite3.connect(f"file:{(tmp / 'settings.db').as_posix()}?mode=ro",
                              uri=True)
        try:
            raw = {k: v for k, v in con.execute("SELECT key, value FROM settings")}
        finally:
            con.close()

        # The exact dictionary shape the app hands to the startup migration.
        data_dict: dict = {}
        for key, value in raw.items():
            try:
                data_dict[key] = json.loads(value)
            except ValueError:
                data_dict[key] = value

        sound_manager.migrate_sound_settings(
            data_dict, sounds_dir=str(sl.packaged_root()))

        before_events = json.loads(raw.get("sound_events", "{}"))
        after_events = data_dict.get("sound_events", {})
        rewritten = [
            (event, cfg.get("file"), after_events.get(event, {}).get("file"))
            for event, cfg in before_events.items()
            if cfg.get("file") != after_events.get(event, {}).get("file")
        ]

        print("COLD START SIMULATION (operator's real settings, on a copy)")
        print(f"events before {len(before_events)}, after {len(after_events)}")
        print(f"REFS_REWRITTEN {len(rewritten)}")
        for row in rewritten[:10]:
            print(f"  {row}")

        ambience_ok = True
        if audio_db.is_file():
            _snapshot(audio_db, tmp / "audio.db")
            store = ambience_store.AmbienceStore(str(tmp / "audio.db"))
            rules_before = [(r.id, r.name, r.sound_ref, r.volume, r.enabled)
                            for r in store.load_rules()]
            seeded = ambience_store.ensure_default_rules(store)
            rules_after = [(r.id, r.name, r.sound_ref, r.volume, r.enabled)
                           for r in store.load_rules()]
            ambience_ok = rules_before == rules_after
            print(f"AMBIENCE_SEEDED {seeded}")
            print(f"AMBIENCE_UNCHANGED {ambience_ok}")
            for rule in rules_after:
                print(f"  {rule}")

        unresolved = [
            event for event, cfg in after_events.items()
            if cfg.get("file") and sl.resolve_sound_ref(str(cfg["file"])) is None
        ]
        print(f"UNRESOLVED_AFTER_COLD_START {len(unresolved)} {unresolved[:5]}")

        ok = not rewritten and ambience_ok and not unresolved
        print("VERDICT", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
