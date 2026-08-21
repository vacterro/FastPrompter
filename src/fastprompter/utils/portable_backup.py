"""Portable backup: exports all silos, snippets, and archive as structured .md files.

Destination: ~/.fastprompter/YYYY-MM-DD/ (profile 1, legacy layout) or
~/.fastprompter/profiles/p<id>/YYYY-MM-DD/ (profile 2+, isolated).
Creates per-category snippet files, silo files, and archive files.
Runs throttled during save_data_to_db (max once per 120s PER PROFILE).

Completion semantics (Phase 6, second pass):

* a snapshot is COMPLETE only if every mandatory export succeeded — the
  ``_COMPLETE`` marker is written LAST, after silos, archive, snippets and
  the manifest.
* the export is built in a ``<date>.partial`` temp directory and published
  atomically only on success; a failed export leaves the previous known-good
  day directory untouched.
* ``last_success_by_profile[profile_id]`` advances only after a successful
  snapshot of that profile, so a failed export stays eligible for an
  immediate retry. Throttle/coalescing are PER PROFILE: profile A's save
  can never suppress profile B's backup.
* every snapshot carries an immutable ``profile_id`` so the async scheduler
  can namespace, throttle and coalesce each profile independently.
"""

import json
import os
import shutil
import time

from fastprompter.core.logging import logger
from fastprompter.utils.path_safety import alloc_fs_names, fs_component
from fastprompter.utils.paths import get_portable_backup_dir, profile_files_root

# Throttle state, one entry PER PROFILE. The old single scalar let one
# profile's recent save silently suppress another profile's backup.
last_success_by_profile: dict = {}
_BACKUP_THROTTLE = 120  # seconds between backups (per profile)

# PERF-008: per-profile backup-request state used to coalesce BEFORE the
# expensive deep copy in capture_snapshot(). `_backup_active` marks a
# profile that already has a pending/in-flight request; while it is set,
# run_portable_backup() records a newer state is wanted and returns WITHOUT
# deep-copying. The completion hook (backup_finished) then clears the
# throttle so the newest state is exported on the next eligible run.
_backup_active: set = set()
_backup_newer_wanted: set = set()
# CORE-002/CORE-003: retain the newest pending IMMUTABLE snapshot per
# profile instead of a boolean or live data reference, so the latest
# committed generation can be dispatched once the current job completes.
_backup_pending_data: dict = {}

_COMPLETE_MARKER = "_COMPLETE"

# The app installs a Qt-backed ASYNC dispatcher here; without one the backup
# runs synchronously (tests, headless use). The sink receives an IMMUTABLE
# deep-copied snapshot, never the live data dict.
_backup_sink = None


def set_backup_sink(sink):
    """Install the app's async portable-backup dispatcher (or None to go
    back to synchronous). The sink is called with an immutable snapshot."""
    global _backup_sink
    _backup_sink = sink
    if sink is None:
        # PERF-008: returning to synchronous mode retires any outstanding
        # coalescing markers (a request left 'active' by an async sink that
        # never completed must not suppress the next run).
        _backup_active.clear()
        _backup_newer_wanted.clear()
        _backup_pending_data.clear()


def capture_snapshot(data, profile_id=1):
    """Deep-copy ONLY the exact fields portable export needs.

    Never hands the worker a reference to the live, mutable data dict: a
    save happening after capture cannot alter what the worker writes. The
    snapshot carries an immutable ``profile_id`` so the async scheduler can
    route/throttle/coalesce each profile independently.
    """
    import copy as _copy
    return {
        "profile_id": int(profile_id or 1),
        "cats_order": list(data.get("cats_order", []) or []),
        "categories": {
            k: [_copy.deepcopy(s) if isinstance(s, dict) else None
                for s in (v or [])]
            for k, v in (data.get("categories") or {}).items()},
        "temp_presets_all": {
            k: list(v) for k, v in (data.get("temp_presets_all") or {}).items()},
        "archive_temp_presets_all": {
            k: list(v)
            for k, v in (data.get("archive_temp_presets_all") or {}).items()},
        # flat aliases too: _per_project falls back to them for legacy data
        # that only ever wrote the active-project alias
        "temp_presets": list(data.get("temp_presets", []) or []),
        "archive_temp_presets": list(data.get("archive_temp_presets", []) or []),
    }


def mark_backup_success(now=None, profile_id=1):
    """The async worker reports a completed snapshot; the throttle advances
    only on success (matching the synchronous path). Per profile: a success
    in one profile never touches another profile's throttle."""
    pid = int(profile_id or 1)
    last_success_by_profile[pid] = now if now is not None else time.time()


def clear_throttle(profile_id=1):
    """Forget a profile's last-success stamp so its next backup is eligible
    immediately (used when the NEWEST snapshot for that profile failed)."""
    last_success_by_profile.pop(int(profile_id or 1), None)


def run_portable_backup(data: dict, profile_id=1) -> None:
    """Export all data as structured .md files. Throttled per profile.

    With an installed async sink, the immutable snapshot (carrying
    ``profile_id``) is dispatched to the worker, which owns throttle
    advancement on success; otherwise the synchronous path below runs.

    PERF-008: the expensive ``capture_snapshot`` deep copy is COALESCED.
    While a request for this profile is already active (pending or in
    flight), repeated eligible saves only record that a newer state is
    wanted -- they never deep-copy the full data universe just to replace
    a pending snapshot. ``backup_finished`` clears the throttle for a
    wanted-newer profile so the newest state is exported on the next run.
    """
    pid = int(profile_id or 1)
    now = time.time()
    if now - last_success_by_profile.get(pid, 0.0) < _BACKUP_THROTTLE:
        return

    if pid in _backup_active:
        # CORE-002: capture immutable committed snapshot immediately, not
        # live mutable dict. Deferred generation must be exactly the state
        # that belonged to the successful save that requested it.
        _backup_newer_wanted.add(pid)
        _backup_pending_data[pid] = capture_snapshot(data, profile_id=pid)
        return
    _backup_active.add(pid)

    snapshot = capture_snapshot(data, profile_id=pid)
    if _backup_sink is not None:
        try:
            _backup_sink(snapshot)
        except Exception:
            logger.exception("portable backup dispatch failed")
            _backup_active.discard(pid)
            _backup_pending_data.pop(pid, None)
        return

    try:
        _do_export(snapshot, profile_id=pid)
    except Exception:
        # A backup that fails silently is worse than no backup: the user
        # believes the snapshot exists. Reach the log file, keep the previous
        # good snapshot, and DO NOT advance the throttle — the next save may
        # retry.
        logger.exception("portable backup FAILED; the previous good snapshot "
                         "is kept and the next save may retry")
        _backup_active.discard(pid)
        return

    last_success_by_profile[pid] = now
    _backup_active.discard(pid)
    _finish_newer_wanted(pid)


def _finish_newer_wanted(pid):
    """A completed synchronous backup: if a newer state was requested while
    it ran, clear the throttle so the very next eligible save captures and
    exports the newest state immediately."""
    if pid in _backup_newer_wanted:
        _backup_newer_wanted.discard(pid)
        last_success_by_profile.pop(pid, None)


def backup_finished(profile_id=1):
    """Called by the async worker on completion of a snapshot. Retires the
    active marker for the profile and, when a newer state was requested
    while it ran, clears the throttle and dispatches the newest pending
    snapshot immediately (CORE-003) without waiting for another save."""
    pid = int(profile_id or 1)
    has_newer = pid in _backup_newer_wanted
    _backup_active.discard(pid)
    if has_newer:
        _backup_newer_wanted.discard(pid)
        last_success_by_profile.pop(pid, None)
        pending_snapshot = _backup_pending_data.pop(pid, None)
        if pending_snapshot is not None and _backup_sink is not None:
            _backup_active.add(pid)
            try:
                _backup_sink(pending_snapshot)
            except Exception:
                logger.exception("portable backup dispatch failed for newest")
                _backup_active.discard(pid)
                _backup_pending_data.pop(pid, None)
        # sync path: throttle already cleared, next save will capture newest
    else:
        _backup_pending_data.pop(pid, None)
        _finish_newer_wanted(pid)


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


def _profile_backup_dir(backup_dir: str, profile_id) -> str:
    """Backup root a profile owns. Profile 1 keeps the legacy flat layout;
    profiles 2+ get an explicit ``profiles/p<id>`` namespace so a backup of
    one profile can never overwrite another's day directory."""
    return profile_files_root(backup_dir, profile_id)


def _do_export(data: dict, profile_id=1) -> None:
    backup_dir = get_portable_backup_dir()
    # Per-day subdirectory, built as an exact snapshot in a temp sibling and
    # published atomically only when every write succeeded. Namespaced per
    # profile (profile 1 = legacy flat layout).
    backup_dir = _profile_backup_dir(backup_dir, profile_id)
    date_str = time.strftime("%Y-%m-%d")
    day_dir = os.path.join(backup_dir, date_str)
    # W2-001: if canonical is missing after a crash window, recover best
    # complete sibling before starting a fresh build
    if not os.path.isdir(day_dir):
        _recover_canonical_day(backup_dir, day_dir, date_str)
    tmp_dir = day_dir + ".partial"
    # W2-009: if a prior build at this .partial path holds a COMPLETE
    # generation (left behind by a double-failure publish, intentionally
    # preserved for manual recovery), do NOT destroy it. Rename it to a
    # unique recovered sibling first so the next export can run safely
    # without deleting the last known-good candidate.
    if os.path.isdir(tmp_dir) and _has_complete_marker(tmp_dir):
        recovered = f"{day_dir}.recovered-{_gen_suffix()}"
        try:
            os.rename(tmp_dir, recovered)
        except OSError:
            # cannot even preserve it: do NOT then rmtree it away
            logger.error(
                "portable backup: COMPLETE recovery generation at %s could "
                "not be preserved; aborting new export rather than destroy it",
                tmp_dir)
            raise
    shutil.rmtree(tmp_dir, ignore_errors=True)

    cats = data.get("cats_order", []) or []
    # One collision-free filesystem component per logical project name,
    # consistent across silos/archive/snippets within this snapshot. Build it
    # from EVERY category actually exported — not only cats_order. DB recovery
    # preserves unknown categories in the per-category stores, so an orphan
    # ("Foo." / "Foo ") would otherwise fall back to its raw name, collide with
    # another, and silently drop one category's export.
    export_cats = set(cats)
    for key in ("temp_presets_all", "archive_temp_presets_all", "categories"):
        store = data.get(key)
        if isinstance(store, dict):
            export_cats.update(store.keys())
    comps = alloc_fs_names([c for c in export_cats if isinstance(c, str)])
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

        # 3. Snippets (by category) — one distinct file per project.
        # W2-008: iterate the AUTHORITATIVE category keys, not only
        # cats_order. DB recovery deliberately preserves categories that are
        # missing from cats_order, so an orphan ("Visible" + "Orphan" both
        # populated) must still be exported and included in the manifest.
        if cats and categories:
            snips_dir = os.path.join(tmp_dir, "snippets")
            os.makedirs(snips_dir, exist_ok=True)
            for cat in categories:
                if not isinstance(cat, str):
                    continue
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
    and the failed new generation is preserved under a distinct
    ``.failed-<suffix>`` name for manual recovery rather than silently lost.
    Double failure (step 2 AND the restore of step 1) keeps BOTH recoverable
    generations on disk: the old one under ``.rollback-<suffix>`` and the new
    COMPLETE one under ``.failed-<suffix>``. This is NOT an atomic swap — it
    is a rollback-safe multi-rename whose guarantee is "no generation is ever
    deleted before its successor is safely published". A failure after step 1
    but before step 2 is exactly the window delete-then-rename used to lose
    data in.
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
            # The previous generation could not be put back. The failed NEW
            # generation must NEVER be destroyed here: it is a complete,
            # recoverable snapshot. It is preserved under a UNIQUE
            # ``.failed-<suffix>`` name — never the ``.partial`` temp path,
            # which is the SAME path the new generation was just built at
            # (rmtree on it would delete the new generation itself, and a
            # second failure would then have nothing left to rename).
            failed = f"{day_dir}.failed-{_gen_suffix()}"
            try:
                os.rename(tmp_dir, failed)
            except OSError as exc:
                # Last resort: the rename failed AND the restore failed. The
                # COMPLETE generation under tmp_dir must still survive — it
                # is the only new snapshot that exists. Leaving it in place
                # costs nothing (the next export removes the .partial dir
                # before rebuilding) and deleting it would destroy the only
                # complete recovery copy. Log both recovery paths loudly so
                # a human can rescue them (P1-7).
                logger.error(
                    "portable backup publish: could not restore the old "
                    "generation (%s) and could not preserve the new one at "
                    "%s (%s). Leaving the COMPLETE new generation at %s for "
                    "manual recovery; the old generation is recoverable from "
                    "%s.",
                    rollback, failed, exc, tmp_dir, rollback)
        else:
            # The previous generation was restored to day_dir, but the NEW
            # one failed to publish. It is a COMPLETE snapshot (the .partial
            # path held a finished build) — deleting it would destroy the
            # user's newest state on a transient volume error. Preserve it
            # under a unique ``.failed-<suffix>`` name (P1-6).
            failed = f"{day_dir}.failed-{_gen_suffix()}"
            try:
                os.rename(tmp_dir, failed)
            except OSError as exc:
                logger.error(
                    "portable backup publish: the previous generation was "
                    "restored but the new one could not be preserved at %s "
                    "(%s); leaving it at %s for manual recovery",
                    failed, exc, tmp_dir)
            else:
                logger.warning(
                    "portable backup publish: the previous generation was "
                    "restored but the new snapshot could not be published; "
                    "the complete new generation is preserved at %s", failed)
        raise
    if os.path.isdir(rollback):
        shutil.rmtree(rollback, ignore_errors=True)


def _gen_suffix():
    import uuid
    return uuid.uuid4().hex[:8]


def _has_complete_marker(directory: str) -> bool:
    """True when `directory` carries the immutable COMPLETE marker left by a
    finished snapshot build.

    Used by the next export to recognise a recovery generation that must be
    preserved, never blindly removed (W2-009)."""
    try:
        return os.path.isfile(os.path.join(directory, _COMPLETE_MARKER))
    except OSError:
        return False


def _recover_canonical_day(backup_root: str, day_dir: str, date_str: str) -> None:
    """If canonical day_dir is missing, promote best complete sibling (W2-001)."""
    if os.path.isdir(day_dir):
        return
    try:
        entries = os.listdir(backup_root)
    except OSError:
        return
    candidates = []
    prefix = date_str + "."
    for e in entries:
        if not e.startswith(prefix):
            continue
        # only recognized sibling types
        if not (e.startswith(date_str + ".rollback-") or e.startswith(date_str + ".failed-") or e.startswith(date_str + ".recovered-") or e == date_str + ".partial"):
            continue
        cand = os.path.join(backup_root, e)
        if not os.path.isdir(cand) or not _has_complete_marker(cand):
            continue
        # also require valid manifest
        meta = os.path.join(cand, "_meta.json")
        try:
            if not os.path.isfile(meta):
                continue
            with open(meta, encoding="utf-8") as f:
                j = json.load(f)
            if not isinstance(j, dict) or not j.get("complete"):
                continue
            exported = j.get("exported_at", "")
        except Exception:
            continue
        candidates.append((exported, cand))
    if not candidates:
        return
    # pick latest exported_at
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    try:
        os.rename(best, day_dir)
        logger.info("portable backup: recovered canonical day from %s", best)
    except OSError:
        logger.error("portable backup: failed to recover canonical day from %s", best)


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
            # W2-008: count every category actually exported above, not
            # only the cats_order subset.
            1 for cat, slots in categories.items()
            for s in (slots or [])
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
