"""Portable backup: exports all silos, snippets, and archive as structured .md files.

Destination: ~/.fastprompter/YYYY-MM-DD/
Creates per-category snippet files, silo files, and archive files.
Runs throttled during save_data_to_db (max once per 120s).
"""

import json
import os
import time

from fastprompter.core.logging import logger
from fastprompter.utils.paths import get_portable_backup_dir

_last_backup_time = 0.0
_BACKUP_THROTTLE = 120  # seconds between backups


def run_portable_backup(data: dict) -> None:
    """Export all data as structured .md files. Throttled to prevent I/O storms."""
    global _last_backup_time
    now = time.time()
    if now - _last_backup_time < _BACKUP_THROTTLE:
        return
    _last_backup_time = now

    try:
        _do_export(data)
    except Exception:
        # A backup that fails silently is worse than no backup: the user
        # believes the snapshot exists. print_exc() goes to a console nobody
        # sees in a windowed build, so this has to reach the log file.
        logger.exception("portable backup failed")


def _safe_name(name: str) -> str:
    """A project name that is legal as a folder name on Windows."""
    import re
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip(" .")
    return cleaned[:60] or "Unnamed"


def _per_project(data: dict, key: str) -> dict:
    """{project: slots} for silos or archive, whatever shape the data is in.

    Prefers the per-category store; falls back to the active-project alias so
    a caller holding only that (an older snapshot, a test) still exports
    something rather than nothing.
    """
    everything = data.get(f"{key}_all")
    if isinstance(everything, dict) and everything:
        return {cat: slots for cat, slots in everything.items()
                if isinstance(slots, list)}
    slots = data.get(key)
    if isinstance(slots, list) and slots:
        cats = data.get("cats_order") or ["Text"]
        return {cats[0]: slots}
    return {}


def _do_export(data: dict) -> None:
    backup_dir = get_portable_backup_dir()
    # Per-day subdirectory
    date_str = time.strftime("%Y-%m-%d")
    day_dir = os.path.join(backup_dir, date_str)
    os.makedirs(day_dir, exist_ok=True)

    # 1. Silos — EVERY project, not just the open one.
    #
    # This used to read data["temp_presets"], which is an alias for the
    # ACTIVE category. A user with five projects therefore had four of them
    # missing from the daily snapshot and no way to know: the folder looked
    # full. Snippets were already exported per project; silos now match.
    silos_dir = os.path.join(day_dir, "silos")
    os.makedirs(silos_dir, exist_ok=True)
    for cat, presets in _per_project(data, "temp_presets").items():
        out_dir = os.path.join(silos_dir, _safe_name(cat))
        for i, text in enumerate(presets):
            if text and text.strip():
                os.makedirs(out_dir, exist_ok=True)
                fname = f"silo_{i+1:03d}.md"
                _write_md(os.path.join(out_dir, fname), text, f"{cat} · Silo {i+1}")

    # 2. Archive silos, same rule
    arc_dir = os.path.join(day_dir, "archive")
    for cat, presets in _per_project(data, "archive_temp_presets").items():
        out_dir = os.path.join(arc_dir, _safe_name(cat))
        for i, text in enumerate(presets):
            if text and text.strip():
                os.makedirs(out_dir, exist_ok=True)
                fname = f"archive_{i+1:03d}.md"
                _write_md(os.path.join(out_dir, fname), text,
                          f"{cat} · Archive Silo {i+1}")

    # 3. Snippets (by category)
    cats = data.get("cats_order", [])
    categories = data.get("categories", {})
    if cats and categories:
        snips_dir = os.path.join(day_dir, "snippets")
        os.makedirs(snips_dir, exist_ok=True)
        for cat in cats:
            slots = categories.get(cat, [])
            cat_snippets = [(i, s) for i, s in enumerate(slots) if s and s.get("text", "").strip()]
            if cat_snippets:
                fname = f"{cat.lower().replace(' ', '_')}.md"
                lines = [f"# {cat} Snippets\n", f"_Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}_\n\n"]
                for idx, slot in cat_snippets:
                    name = slot.get("name", f"Snippet {idx+1}")
                    text = slot["text"]
                    lines.append(f"## {idx+1}. {name}\n\n{text}\n\n---\n\n")
                _write_raw(os.path.join(snips_dir, fname), "".join(lines))

    # Write metadata file
    meta_path = os.path.join(day_dir, "_meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                # counted over every project, like the export itself
                "silo_count": sum(
                    1 for slots in _per_project(data, "temp_presets").values()
                    for p in slots if p and p.strip()),
                "archive_count": sum(
                    1 for slots in _per_project(data, "archive_temp_presets").values()
                    for p in slots if p and p.strip()),
                "snippet_count": sum(1 for cat in cats for s in categories.get(cat, []) if s and s.get("text", "").strip())
            }, f, indent=2)
    except Exception:
        logger.warning("portable backup: could not write the day manifest",
                       exc_info=True)

    # Cleanup: keep last 7 day dirs
    _cleanup_old_backups(backup_dir, max_days=7)


def _write_md(path: str, text: str, title: str) -> None:
    """Write a single .md file with a title header."""
    content = f"# {title}\n\n{text}\n"
    _write_raw(path, content)


def _write_raw(path: str, content: str) -> None:
    """Atomically write a file using temp + rename."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        logger.exception("portable backup: could not write %s", path)


def _cleanup_old_backups(backup_dir: str, max_days: int = 7) -> None:
    """Remove day directories older than max_days."""
    try:
        now = time.time()
        for entry in os.listdir(backup_dir):
            entry_path = os.path.join(backup_dir, entry)
            if os.path.isdir(entry_path) and entry[0].isdigit():
                try:
                    dir_time = time.mktime(time.strptime(entry, "%Y-%m-%d"))
                    if now - dir_time > max_days * 86400:
                        import shutil
                        shutil.rmtree(entry_path, ignore_errors=True)
                except (ValueError, OSError):
                    # not a date-named folder, or it is busy: leave it alone
                    logger.debug("backup cleanup skipped %s", entry_path,
                                 exc_info=True)
    except Exception:
        logger.warning("portable backup: cleanup pass failed", exc_info=True)
