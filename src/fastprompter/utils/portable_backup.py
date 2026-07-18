"""Portable backup: exports all silos, snippets, and archive as structured .md files.

Destination: ~/.fastprompter/YYYY-MM-DD/
Creates per-category snippet files, silo files, and archive files.
Runs throttled during save_data_to_db (max once per 120s).
"""

import json
import os
import time

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
        import traceback
        traceback.print_exc()


def _do_export(data: dict) -> None:
    backup_dir = get_portable_backup_dir()
    # Per-day subdirectory
    date_str = time.strftime("%Y-%m-%d")
    day_dir = os.path.join(backup_dir, date_str)
    os.makedirs(day_dir, exist_ok=True)

    # 1. Silos (temp_presets)
    silos_dir = os.path.join(day_dir, "silos")
    os.makedirs(silos_dir, exist_ok=True)
    presets = data.get("temp_presets", [])
    for i, text in enumerate(presets):
        if text and text.strip():
            fname = f"silo_{i+1:03d}.md"
            _write_md(os.path.join(silos_dir, fname), text, f"Silo {i+1}")

    # 2. Archive silos
    arc_presets = data.get("archive_temp_presets", [])
    if arc_presets:
        arc_dir = os.path.join(day_dir, "archive")
        os.makedirs(arc_dir, exist_ok=True)
        for i, text in enumerate(arc_presets):
            if text and text.strip():
                fname = f"archive_{i+1:03d}.md"
                _write_md(os.path.join(arc_dir, fname), text, f"Archive Silo {i+1}")

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
                "silo_count": sum(1 for p in presets if p.strip()),
                "archive_count": sum(1 for p in arc_presets if p.strip()),
                "snippet_count": sum(1 for cat in cats for s in categories.get(cat, []) if s and s.get("text", "").strip())
            }, f, indent=2)
    # TODO: BUG: Silent blanket exception handler swallows errors

    except Exception:
        pass

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
        import traceback
        traceback.print_exc()


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
                    pass
    # TODO: BUG: Silent blanket exception handler swallows errors

    except Exception:
        pass
