"""Portable backup: exports all silos, snippets, and archive as structured .md files.

Destination: ~/.fastprompter/YYYY-MM-DD/
Creates per-category snippet files, silo files, and archive files.
Runs throttled during save_data_to_db (max once per 120s).

Completion semantics (Phase 6, second pass):

* a snapshot is COMPLETE only if every mandatory export succeeded — the
  ``_COMPLETE`` marker is written LAST, after silos, archive, snippets and
  the manifest.
* the export is built in a ``<date>.partial`` temp directory and published
  atomically only on success; a failed export leaves the previous known-good
  day directory untouched.
* ``_last_backup_time`` advances only after a successful snapshot, so a
  failed export stays eligible for an immediate retry.
"""

import json
import os
import shutil
import time

from fastprompter.core.logging import logger
from fastprompter.utils.path_safety import alloc_fs_names, fs_component
from fastprompter.utils.paths import get_portable_backup_dir

_last_backup_time = 0.0
_BACKUP_THROTTLE = 120  # seconds between backups

_COMPLETE_MARKER = "_COMPLETE"


def run_portable_backup(data: dict) -> None:
    """Export all data as structured .md files. Throttled to prevent I/O storms."""
    global _last_backup_time
    now = time.time()
    if now - _last_backup_time < _BACKUP_THROTTLE:
        return

    try:
        _do_export(data)
    except Exception:
        # A backup that fails silently is worse than no backup: the user
        # believes the snapshot exists. Reach the log file, keep the previous
        # good snapshot, and DO NOT advance the throttle — the next save may
        # retry.
        logger.exception("portable backup FAILED; the previous good snapshot "
                         "is kept and the next save may retry")
        return

    _last_backup_time = now


def _safe_name(name: str) -> str:
    """One safe, deterministic filesystem component for a project name.

    A thin wrapper over the shared codec: hostile names get a readable
    prefix plus a stable digest, so two different logical names can never
    collapse onto the same path.
    """
    return fs_component(name)[0]


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
    # Per-day subdirectory, built as an exact snapshot in a temp sibling and
    # published atomically only when every write succeeded.
    date_str = time.strftime("%Y-%m-%d")
    day_dir = os.path.join(backup_dir, date_str)
    tmp_dir = day_dir + ".partial"
    shutil.rmtree(tmp_dir, ignore_errors=True)

    cats = data.get("cats_order", []) or []
    # one collision-free filesystem component per logical project name,
    # consistent across silos/archive/snippets within this snapshot
    comps = alloc_fs_names([c for c in cats if isinstance(c, str)])
    categories = data.get("categories", {})

    try:
        os.makedirs(tmp_dir, exist_ok=True)

        # 1. Silos — EVERY project, not just the open one.
        silos_dir = os.path.join(tmp_dir, "silos")
        os.makedirs(silos_dir, exist_ok=True)
        for cat, presets in _per_project(data, "temp_presets").items():
            out_dir = os.path.join(silos_dir, comps.get(cat, _safe_name(cat)))
            for i, text in enumerate(presets):
                if text and text.strip():
                    os.makedirs(out_dir, exist_ok=True)
                    fname = f"silo_{i+1:03d}.md"
                    _write_md(os.path.join(out_dir, fname), text,
                              f"{cat} · Silo {i+1}")

        # 2. Archive silos, same rule
        arc_dir = os.path.join(tmp_dir, "archive")
        os.makedirs(arc_dir, exist_ok=True)
        for cat, presets in _per_project(data, "archive_temp_presets").items():
            out_dir = os.path.join(arc_dir, comps.get(cat, _safe_name(cat)))
            for i, text in enumerate(presets):
                if text and text.strip():
                    os.makedirs(out_dir, exist_ok=True)
                    fname = f"archive_{i+1:03d}.md"
                    _write_md(os.path.join(out_dir, fname), text,
                              f"{cat} · Archive Silo {i+1}")

        # 3. Snippets (by category) — one distinct file per project
        if cats and categories:
            snips_dir = os.path.join(tmp_dir, "snippets")
            os.makedirs(snips_dir, exist_ok=True)
            for cat in cats:
                slots = categories.get(cat, []) or []
                cat_snippets = [(i, s) for i, s in enumerate(slots)
                                if s and s.get("text", "").strip()]
                if cat_snippets:
                    fname = comps.get(cat, _safe_name(cat)) + ".md"
                    lines = [f"# {cat} Snippets\n",
                             f"_Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}_\n\n"]
                    for idx, slot in cat_snippets:
                        name = slot.get("name", f"Snippet {idx+1}")
                        text = slot["text"]
                        lines.append(f"## {idx+1}. {name}\n\n{text}\n\n---\n\n")
                    _write_raw(os.path.join(snips_dir, fname), "".join(lines))

        # 4. Manifest — written before the COMPLETE marker, still mandatory:
        #   a failure here aborts the snapshot
        _write_manifest(tmp_dir, data, cats, categories)

        # 5. The COMPLETE marker — LAST, so a partial snapshot can never carry
        #    it; its absence is how a partial snapshot is recognised.
        _write_raw(os.path.join(tmp_dir, _COMPLETE_MARKER),
                   f"complete {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Publish with rollback: the old day_dir is the last known-good snapshot
    # and must survive ANY intermediate failure. The old generation is
    # relocated to a unique sibling, the new one is renamed in, and only then
    # is the relocated old one discarded.
    _publish_snapshot(tmp_dir, day_dir)

    # Cleanup: keep last 7 day dirs
    _cleanup_old_backups(backup_dir, max_days=7)


def _publish_snapshot(tmp_dir, day_dir):
    """Swap a freshly-built snapshot in WITHOUT ever losing the previous
    known-good generation.

    Sequence (all renames on the same volume):
      1. rename previous day_dir -> unique rollback sibling
      2. rename new tmp_dir -> day_dir
      3. only after 2 succeeds, remove the rollback sibling

    If step 1 fails the previous generation is untouched and the new temp is
    discarded. If step 2 fails the previous generation is restored to day_dir
    and the failed new generation is preserved under a distinct name for
    manual recovery rather than silently lost. A failure after step 1 but
    before step 2 is exactly the window delete-then-rename used to lose data
    in.
    """
    rollback = f"{day_dir}.rollback-{_gen_suffix()}"
    if os.path.isdir(day_dir):
        try:
            os.rename(day_dir, rollback)
        except OSError:
            # cannot relocate the old generation: keep it, drop the new one
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
    try:
        os.rename(tmp_dir, day_dir)
    except OSError:
        restored = False
        if os.path.isdir(rollback):
            try:
                os.rename(rollback, day_dir)
                restored = True
            except OSError:
                pass
        if not restored:
            # the previous generation could not be put back; keep the failed
            # new one under a distinct name so nothing is silently lost
            failed = f"{day_dir}.partial"
            shutil.rmtree(failed, ignore_errors=True)
            try:
                os.rename(tmp_dir, failed)
            except OSError:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    if os.path.isdir(rollback):
        shutil.rmtree(rollback, ignore_errors=True)


def _gen_suffix():
    import uuid
    return uuid.uuid4().hex[:8]


def _write_manifest(tmp_dir, data, cats, categories):
    meta_path = os.path.join(tmp_dir, "_meta.json")
    _write_raw(meta_path, json.dumps({
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "complete": True,
        # counted over every project, like the export itself
        "silo_count": sum(
            1 for slots in _per_project(data, "temp_presets").values()
            for p in slots if p and p.strip()),
        "archive_count": sum(
            1 for slots in _per_project(data, "archive_temp_presets").values()
            for p in slots if p and p.strip()),
        "snippet_count": sum(
            1 for cat in cats
            for s in (categories.get(cat, []) or [])
            if s and s.get("text", "").strip())
    }, indent=2))


def _write_md(path: str, text: str, title: str) -> None:
    """Write a single .md file with a title header."""
    content = f"# {title}\n\n{text}\n"
    _write_raw(path, content)


def _write_raw(path: str, content: str) -> None:
    """Atomically write a file using temp + rename. RAISES on failure.

    A portable snapshot is all-or-nothing: a failed write must propagate so
    the snapshot is never labelled complete. The partial temp file is
    removed and the error surfaces to run_portable_backup's failure path.
    """
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


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
                        shutil.rmtree(entry_path, ignore_errors=True)
                except (ValueError, OSError):
                    # not a date-named folder, or it is busy: leave it alone
                    logger.debug("backup cleanup skipped %s", entry_path,
                                 exc_info=True)
    except Exception:
        logger.warning("portable backup: cleanup pass failed", exc_info=True)
