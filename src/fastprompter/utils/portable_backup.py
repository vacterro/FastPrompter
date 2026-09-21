"""Portable backup: exports all silos, snippets, and archive as structured .md files.

Destination: ~/.fastprompter/YYYY-MM-DD/ (profile 1, legacy layout) or
~/.fastprompter/profiles/p<id>/YYYY-MM-DD/ (profile 2+, isolated).
Creates per-category snippet files, silo files, and archive files.
Runs throttled during save_data_to_db (max once per 120s PER PROFILE).

Completion semantics (Phase 6, second pass):

* a snapshot is COMPLETE only if every mandatory export succeeded — the
  ``_COMPLETE`` marker is written LAST, after silos, archive, snippets and
  the manifest.
* the export is built in a FRESH per-generation scratch directory
  (``<date>.partial-<generation>``) and published atomically only on success;
  a failed export leaves the previous known-good day directory untouched. The
  legacy fixed ``<date>.partial`` name is still recognised for recovery, but
  is never reused as a construction root (W2-002).
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
import threading
import time

from fastprompter.core.logging import logger
from fastprompter.utils.path_safety import alloc_fs_names, fs_component, unique_temp_path
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
# PERF-005 (corrective, T-1286): while a job is active, a superseding save
# records only its INTENTION -- the committed exported-content generation --
# instead of deep-copying the whole project per save.  A mutable LIVE data
# reference is NOT generation ownership: the deferred snapshot is
# materialised by backup_finished() from the COMMITTED VIEW the caller
# registered for that exact generation, never from whatever the live dict
# happens to contain when the previous worker finishes.
_backup_pending_gen: dict = {}
# PERF-005: the newest committed exported view per profile, registered by the
# owner of committed truth at each successful DB commit from structures the
# commit already built (zero extra copying).  ``gen`` is the exported-content
# generation the view represents; the row sets are immutable by contract and
# are replaced, never mutated, so a new commit can never rewrite an older
# generation's content.
_committed_view_by_profile: dict = {}

# PERF-003 (audit acb-mt9141yi): per-profile record of what was already
# exported, keyed by the caller's exported-content generation and calendar
# day. A save that changed only non-exported domains (settings churn) with
# an already-represented generation skips the O(project) snapshot entirely;
# a new calendar day re-arms one unchanged-content snapshot per profile.
_last_exported_gen_by_profile: dict = {}
_last_exported_day_by_profile: dict = {}

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
        _backup_pending_gen.clear()
        _committed_view_by_profile.clear()


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


def note_committed_view(profile_id=1, content_gen=None, *, cats_order=(),
                        preset_rows=(), temp_rows=(), arc_rows=()):
    """Retain the newest COMMITTED exported view for a profile (PERF-005).

    Called by the owner of committed truth (``FastPrompterState``) after a
    successful commit, with the row sets that commit already built -- so the
    retention itself costs no copying. The materialiser rebuilds a plain
    exported shape from these rows exactly once, when the active worker
    finishes; ``content_gen`` names the exported-content generation the view
    represents, and the two are stored together so identity and content are
    inseparable.

    Contract: the caller hands over structures it will not mutate afterwards.
    Each commit builds NEW sets and replaces this entry wholesale, so an older
    generation's view can never be rewritten by a later commit.
    """
    pid = int(profile_id or 1)
    _committed_view_by_profile[pid] = {
        "gen": None if content_gen is None else int(content_gen),
        "cats_order": tuple(cats_order or ()),
        "preset_rows": preset_rows,
        "temp_rows": temp_rows,
        "arc_rows": arc_rows,
    }


def _rows_to_slots(rows):
    """``{(cat, index, content)}`` -> ``{cat: [content, ...]}`` index-ordered.

    Row presence IS silo existence (T-1222): every committed row, including an
    empty one, is part of the exported extent.
    """
    slots: dict = {}
    for cat, index, content in rows:
        bucket = slots.setdefault(cat, [])
        while len(bucket) <= index:
            bucket.append("")
        bucket[index] = content or ""
    return slots


def _project_committed_view(view: dict) -> dict:
    """Rebuild the exported data shape from a committed view.

    The result is a fresh plain structure whose leaves come only from the
    committed rows; it is what the ONE deferred materialisation captures.
    Flat aliases stay empty because the per-category store is authoritative
    here (``_per_project`` prefers it), and the active-category alias is
    runtime state that is not part of the committed generation.
    """
    categories: dict = {}
    for cat, index, name, text, last_edited in view.get("preset_rows", ()):
        bucket = categories.setdefault(cat, [])
        while len(bucket) <= index:
            bucket.append(None)
        bucket[index] = {"name": name, "text": text,
                         "last_edited": last_edited}
    return {
        "cats_order": list(view.get("cats_order", ())),
        "categories": categories,
        "temp_presets_all": _rows_to_slots(view.get("temp_rows", ())),
        "archive_temp_presets_all": _rows_to_slots(view.get("arc_rows", ())),
        "temp_presets": [],
        "archive_temp_presets": [],
    }


def _materialize_committed(pid: int, gen):
    """The ONE deferred materialisation: committed truth -> immutable
    snapshot, labelled with the exact generation the committed view carries.
    """
    pending_snapshot = capture_snapshot(
        _project_committed_view(_committed_view_by_profile[pid]),
        profile_id=pid)
    if gen is not None:
        pending_snapshot["_content_gen"] = gen
    return pending_snapshot


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


def abandon_inflight(profile_id=1) -> None:
    """A shutdown dropped this profile's in-flight snapshot (worker retired
    before its completion could arrive). Retire the coalescing markers too:
    the active/newer intents are only resolved by ``backup_finished``, so a
    surviving marker would silently refuse every future request for the
    profile — a permanent backup outage after one mid-session shutdown.
    Dropping the intent loses nothing: the next eligible save captures the
    then-current committed state."""
    pid = int(profile_id or 1)
    _backup_active.discard(pid)
    _backup_newer_wanted.discard(pid)
    _backup_pending_data.pop(pid, None)
    _backup_pending_gen.pop(pid, None)


def run_portable_backup(data: dict, profile_id=1, content_gen=None) -> None:
    """Export all data as structured .md files. Throttled per profile.

    With an installed async sink, the immutable snapshot (carrying
    ``profile_id``) is dispatched to the worker, which owns throttle
    advancement on success; otherwise the synchronous path below runs.

    PERF-008 (as amended by CORE-002 and PERF-005): while a request for this
    profile is already active, repeated eligible saves never dispatch to the
    sink again -- and they no longer materialise a snapshot each either.  Only
    the newest committed content generation is recorded as an intention;
    ``backup_finished`` retires the active marker and takes exactly ONE
    immutable snapshot from the COMMITTED VIEW registered for that generation
    (``note_committed_view``), so a deferred generation is exactly the state
    of the save that requested it while a 20-save burst costs one capture plus
    one deferred materialisation -- never twenty-one. Live mutable ``data`` is
    never retained as ownership for a deferred generation.

    PERF-003: when the caller supplies ``content_gen`` (the profile's
    exported-content generation), a save whose generation was already
    exported AND whose calendar day matches the last export skips the whole
    capture — settings-only churn can no longer periodically copy and write
    an unchanged project. Any silo/snippet/archive/category-content change
    bumps the generation and re-arms; a new calendar day re-arms exactly one
    unchanged-content snapshot; explicit backup paths call without
    ``content_gen`` and always capture.
    """
    pid = int(profile_id or 1)
    now = time.time()
    if now - last_success_by_profile.get(pid, 0.0) < _BACKUP_THROTTLE:
        return

    # PERF-003: unchanged-exported-content short-circuit. Evaluated AFTER the
    # throttle so a throttled save costs nothing either way, and BEFORE any
    # deep copy / coalescing bookkeeping.
    if content_gen is not None \
            and _last_exported_gen_by_profile.get(pid) == content_gen \
            and _last_exported_day_by_profile.get(pid) == _today():
        return

    if pid in _backup_active:
        # PERF-005: coalesce BEFORE materialisation.  The previous shape
        # deep-copied the whole project on EVERY superseding eligible save
        # (audit measured 21 capture_snapshot() calls for 21 generations)
        # even though only the newest pending generation survives.  Only the
        # newest committed generation is recorded as an intention; its
        # CONTENT is sourced later from the committed view registered for
        # that exact generation.  W2-008: the pending intention carries the
        # EXACT content generation it represents, so a successful redispatch
        # can advance _last_exported_gen_by_profile.
        _backup_newer_wanted.add(pid)
        if content_gen is not None:
            _backup_pending_gen[pid] = content_gen
        else:
            _backup_pending_gen.pop(pid, None)
        return
    _backup_active.add(pid)

    snapshot = capture_snapshot(data, profile_id=pid)
    if content_gen is not None:
        # PERF-003: the async completion path reads the generation back off
        # the immutable snapshot to mark what a success represented.
        snapshot["_content_gen"] = content_gen
    # A fresh snapshot of the CURRENT state supersedes any stale coalesced
    # pending state left by a CORE-005 redispatch failure.
    _backup_pending_data.pop(pid, None)
    _backup_pending_gen.pop(pid, None)
    _backup_newer_wanted.discard(pid)
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
    _mark_exported(pid, content_gen)
    _backup_active.discard(pid)
    _finish_newer_wanted(pid)


def _today():
    return time.strftime("%Y-%m-%d")


def _mark_exported(pid, content_gen=None):
    """Record what this profile's latest successful export represented."""
    if content_gen is not None:
        _last_exported_gen_by_profile[pid] = content_gen
    _last_exported_day_by_profile[pid] = _today()


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
    snapshot immediately (CORE-003) without waiting for another save.

    PERF-005: the deferred snapshot is materialised HERE, exactly once, from
    the committed view registered for the pending generation.  A generation
    whose committed view is absent is NEVER fabricated from live memory: the
    throttle is cleared so the next eligible save dispatches a fresh capture
    at a moment when live data IS the committed state.  A CORE-005 failed
    redispatch keeps the already-materialised immutable snapshot pending, so
    the newest state stays retryable without a second capture."""
    pid = int(profile_id or 1)
    has_newer = pid in _backup_newer_wanted
    _backup_active.discard(pid)
    if has_newer:
        _backup_newer_wanted.discard(pid)
        last_success_by_profile.pop(pid, None)
        pending_snapshot = _backup_pending_data.pop(pid, None)
        if pending_snapshot is None:
            gen = _backup_pending_gen.pop(pid, None)
            view = _committed_view_by_profile.get(pid)
            if view is not None and (gen is None or view["gen"] == gen):
                pending_snapshot = _materialize_committed(pid, gen)
        if pending_snapshot is not None and _backup_sink is not None:
            _backup_active.add(pid)
            try:
                _backup_sink(pending_snapshot)
            except Exception:
                logger.exception("portable backup dispatch failed for newest")
                _backup_active.discard(pid)
                # CORE-005: failure while redispatching the coalesced newest
                # snapshot must NOT destroy the retry state. Restore the exact
                # pending snapshot and re-arm the newer marker atomically, so
                # an obsolete worker completion can never advance the throttle
                # and the next eligible save/drain retries this snapshot.
                _backup_pending_data[pid] = pending_snapshot
                _backup_newer_wanted.add(pid)
        # sync path: throttle already cleared, next save will capture newest
    else:
        _backup_pending_data.pop(pid, None)
        _backup_pending_gen.pop(pid, None)
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


def _discard_incomplete_scratch(path: str) -> None:
    """Best-effort removal of an INCOMPLETE scratch tree (W2-002).

    Deliberately NOT ``rmtree(ignore_errors=True)``: a survivor is reported
    instead of being silently pretended away. Correctness no longer depends on
    the removal succeeding — every generation is built in a brand-new scratch
    root — but a leaked tree must stay visible in the log.
    """
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning(
            "portable backup: incomplete scratch tree %s could not be "
            "removed (%s); it is never reused for a new generation", path, exc)


def _alloc_scratch_root(day_dir: str) -> str:
    """Create and return a NEW, provably empty scratch root for ONE generation.

    W2-002: construction must begin from storage that is empty BY
    CONSTRUCTION, never from a path whose emptiness depends on a best-effort
    recursive delete. ``rmtree`` can fail on Windows (locked/read-only files,
    antivirus, sharing violations); reusing such a tree with
    ``makedirs(..., exist_ok=True)`` merged artifacts of a failed generation
    into the current one and then stamped the result ``_COMPLETE``.

    ``os.makedirs`` without ``exist_ok`` fails when the name already exists, so
    an existing directory is never adopted — a colliding suffix is skipped.
    """
    for _ in range(_SCRATCH_ATTEMPTS):
        candidate = f"{day_dir}.partial-{_gen_suffix()}"
        try:
            os.makedirs(candidate)
        except FileExistsError:
            continue
        if os.listdir(candidate):
            # Unreachable for a directory we just created; kept as a cheap
            # invariant so a reused/contaminated root can never be built in.
            _discard_incomplete_scratch(candidate)
            continue
        return candidate
    raise RuntimeError(
        "portable backup: could not allocate a fresh scratch directory for "
        f"{day_dir}")


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
    # W2-009: if the LEGACY fixed ``<day>.partial`` path holds a COMPLETE
    # generation (left behind by a double-failure publish, intentionally
    # preserved for manual recovery), do NOT destroy it. Rename it to a
    # unique recovered sibling first so the next export can run safely
    # without deleting the last known-good candidate.
    legacy_tmp = day_dir + ".partial"
    if os.path.isdir(legacy_tmp) and _has_complete_marker(legacy_tmp):
        recovered = f"{day_dir}.recovered-{_gen_suffix()}"
        try:
            os.rename(legacy_tmp, recovered)
        except OSError:
            # cannot even preserve it: do NOT then rmtree it away
            logger.error(
                "portable backup: COMPLETE recovery generation at %s could "
                "not be preserved; aborting new export rather than destroy it",
                legacy_tmp)
            raise
    # W2-002: an INCOMPLETE legacy scratch tree is no longer the construction
    # root, so a survivor can never be merged into a new generation. Remove it
    # best-effort (and loudly if it survives) rather than silently trusting
    # ``rmtree(ignore_errors=True)`` to have emptied a path we then rebuilt in.
    if os.path.isdir(legacy_tmp):
        _discard_incomplete_scratch(legacy_tmp)

    # W2-002: build in a FRESH per-generation root — empty by construction, so
    # stale files from a failed generation can never be published inside a tree
    # carrying a new ``_COMPLETE`` marker. If this cannot be created, nothing
    # has been written yet and the canonical day dir is left untouched.
    tmp_dir = _alloc_scratch_root(day_dir)

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
        # ``tmp_dir`` was created fresh and empty by ``_alloc_scratch_root``
        # (W2-002): only this generation's own artifacts ever land beneath it.

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
        # W2-002: best-effort, but never silent — and never a path a later
        # export could adopt, because each generation gets its own scratch root.
        _discard_incomplete_scratch(tmp_dir)
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
            # ``.failed-<suffix>`` name — never the scratch path, which is
            # where the new generation was just built (rmtree on it would
            # delete the new generation itself, and a second failure would
            # then have nothing left to rename).
            failed = f"{day_dir}.failed-{_gen_suffix()}"
            try:
                os.rename(tmp_dir, failed)
            except OSError as exc:
                # Last resort: the rename failed AND the restore failed. The
                # COMPLETE generation under tmp_dir must still survive — it
                # is the only new snapshot that exists. Leaving it in place
                # costs nothing (each generation gets its OWN fresh scratch
                # root, so a survivor is never reused) and deleting it would
                # destroy the only complete recovery copy. Log both recovery paths loudly so
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
            # one failed to publish. It is a COMPLETE snapshot (the scratch
            # root held a finished build) — deleting it would destroy the
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


def _is_valid_complete_generation(directory: str) -> bool:
    """True when `directory` is a USABLE complete backup generation.

    ONE validator shared by recovery selection and retention (W2-004): the
    directory must exist, carry the ``_COMPLETE`` marker, hold a parseable
    ``_meta.json`` whose ``complete`` flag is true. Retention must never treat
    a canonical pathname as proof of a safe canonical backup — only a
    generation that passes this exact check may authorize pruning its recovery
    siblings.
    """
    try:
        if not os.path.isdir(directory):
            return False
        if not _has_complete_marker(directory):
            return False
        meta = os.path.join(directory, "_meta.json")
        if not os.path.isfile(meta):
            return False
        with open(meta, encoding="utf-8") as f:
            j = json.load(f)
        return isinstance(j, dict) and bool(j.get("complete"))
    except Exception:
        return False


_GEN_LOCK = threading.Lock()
_GEN_LAST_NS = 0


def _new_generation_identity() -> tuple:
    """``(generation_ns, generation_id)`` for a manifest being written.

    W2-003: ``generation_ns`` is the orderable, finer-than-second identity
    recovery sorts by; ``generation_id`` is a collision-resistant label so two
    generations can still be told apart when a clock cannot (a manifest is
    copied, the clock is corrected backwards).

    The stamp is STRICTLY increasing in-process: Windows' clock resolution can
    hand two consecutive ``time.time_ns()`` calls the identical value (measured
    on the W2-003 regression), which would leave recovery ordering those two
    generations by the random id. A monotonic bump keeps the persisted
    chronology total without pretending a precision the platform lacks.
    """
    global _GEN_LAST_NS
    with _GEN_LOCK:
        ns = time.time_ns()
        if ns <= _GEN_LAST_NS:
            ns = _GEN_LAST_NS + 1
        _GEN_LAST_NS = ns
    return ns, _gen_suffix() + _gen_suffix()


def _generation_time_ns(meta: dict):
    """Absolute generation time in UTC nanoseconds, or None when unknown.

    W2-003: a manifest's ``exported_at`` has ONE-SECOND resolution, so two
    complete generations created within the same second are indistinguishable
    to it — and the random UUID suffix carries no chronology at all. Every
    generation therefore persists ``generation_ns`` (``time.time_ns()``) plus
    a collision-resistant ``generation_id``, and recovery orders primarily by
    that field. A legacy manifest without it falls back to the second-
    resolution stamp, converted to the same nanosecond unit so a genuinely
    newer legacy generation still wins; an unparsable/absent stamp is unknown
    (``None``) rather than silently treated as oldest.
    """
    ns = meta.get("generation_ns")
    if isinstance(ns, bool):
        ns = None
    if isinstance(ns, int):
        return ns
    if isinstance(ns, str) and ns.strip().isdigit():
        return int(ns.strip())
    stamp = meta.get("exported_at")
    if isinstance(stamp, str) and stamp:
        try:
            return int(time.mktime(
                time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))) * 1_000_000_000
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _recover_canonical_day(backup_root: str, day_dir: str, date_str: str) -> None:
    """If canonical day_dir is missing, promote the best complete sibling.

    W2-003: promotion must be REPEATABLE. Selection is a total order over an
    absolute generation time (``generation_ns``, or the legacy second-
    resolution ``exported_at`` in the same unit) — never ``os.listdir()``
    order. Fail-closed: when the newest generation time is shared, or any
    candidate's time is unknown, nothing is promoted and every candidate is
    left on disk for manual recovery. Refusing here cannot lose data: a
    backup export that found no canonical day simply builds a fresh
    generation, and retention preserves the siblings until a validated
    canonical exists for the date.
    """
    if os.path.isdir(day_dir):
        return
    try:
        entries = os.listdir(backup_root)
    except OSError:
        return
    candidates = []
    unknown = []
    for e in entries:
        # W2-002: ONE grammar, so a complete generation left in either the
        # legacy ``.partial`` or a per-generation ``.partial-<gen>`` scratch
        # root is still recoverable — an unrelated directory is not.
        if _backup_sibling_kind(e, date_str) is None:
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
            ns = _generation_time_ns(j)
        except Exception:
            continue
        if ns is None:
            unknown.append(cand)
        else:
            candidates.append((ns, cand))
    if not candidates:
        if unknown:
            logger.error(
                "portable backup: %d complete generation(s) for %s carry no "
                "orderable generation identity; refusing automatic promotion "
                "(preserved for manual recovery): %s",
                len(unknown), date_str, unknown)
        return
    if unknown:
        # A candidate whose time is unknown could be the newest one; choosing
        # any of the known ones could therefore discard newer state.
        logger.error(
            "portable backup: refusing automatic promotion for %s: %d "
            "generation(s) have no orderable generation identity: %s",
            date_str, len(unknown), unknown)
        return
    best_ns = max(ns for ns, _cand in candidates)
    newest = [cand for ns, cand in candidates if ns == best_ns]
    if len(newest) > 1:
        # An exact identity tie: enumerating the filesystem must never decide
        # which generation state survives.
        logger.error(
            "portable backup: refusing automatic promotion for %s: %d "
            "complete generations share the newest identity %s; recover "
            "manually from %s",
            date_str, len(newest), best_ns, sorted(newest))
        return
    best = newest[0]
    try:
        os.rename(best, day_dir)
        logger.info("portable backup: recovered canonical day from %s", best)
    except OSError:
        logger.error("portable backup: failed to recover canonical day from %s", best)


def _write_manifest(tmp_dir, data, cats, categories):
    meta_path = os.path.join(tmp_dir, "_meta.json")
    # W2-003: ``exported_at`` stays for humans; recovery orders by the
    # orderable generation identity persisted alongside it. Both are computed
    # ONCE here so the manifest is internally consistent.
    generation_ns, generation_id = _new_generation_identity()
    _write_raw(meta_path, json.dumps({
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generation_ns": generation_ns,
        "generation_id": generation_id,
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
    tmp_path = unique_temp_path(path, "pbackup")
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


# Recovery-generation markers produced by _publish_snapshot's rollback-safe
# multi-rename. A complete recoverable generation carries one of these suffixes
# after the canonical YYYY-MM-DD day; the grammar must be recognised by
# retention so a complete snapshot tree is never silently kept forever (W2-006).
_RECOVERY_SUFFIXES = ("failed", "rollback", "recovered")


# W2-002: how many fresh scratch names to try before giving up. Every attempt
# CREATES a new directory, so a collision is only ever a stale name.
_SCRATCH_ATTEMPTS = 8


def _backup_sibling_kind(entry: str, date_str: str):
    """Kind of a recognised ``date_str`` day sibling, or None when unrelated.

    ONE grammar shared by canonical recovery and retention (W2-002/W2-006):

    * ``""``        — the canonical day itself;
    * ``"partial"`` — transient scratch, either the legacy fixed
      ``<day>.partial`` or the per-generation ``<day>.partial-<generation>``;
    * one of ``_RECOVERY_SUFFIXES`` — a complete recoverable generation left
      by ``_publish_snapshot``'s rollback-safe multi-rename.

    Anything else is outside the grammar and must be left alone.
    """
    if entry == date_str:
        return ""
    if not entry.startswith(date_str + "."):
        return None
    suffix = entry[len(date_str) + 1:]
    if suffix == "partial" or suffix.startswith("partial-"):
        return "partial"
    for kind in _RECOVERY_SUFFIXES:
        if suffix.startswith(kind + "-"):
            return kind
    return None


def _cleanup_old_backups(backup_dir: str, max_days: int = 7) -> None:
    """Remove day directories older than max_days.

    W2-006: retention understands the project's recovery-generation naming. A
    canonical ``YYYY-MM-DD`` day dir follows normal retention. The first-class
    complete generations ``YYYY-MM-DD.failed-<s>``, ``.rollback-<s>`` and
    ``.recovered-<s>`` are pruned only when a safe canonical generation for the
    same date exists (or, for scratch temps — legacy ``.partial`` or
    per-generation ``.partial-<gen>`` — always when old) — an old
    suffix that is the ONLY valid backup is preserved, never blindly deleted.
    Unrelated digit-prefixed directories outside this grammar are left alone.
    """
    try:
        now = time.time()
        entries = os.listdir(backup_dir)
        # Parse every candidate once. A date dir may be the canonical day, a
        # recognised recovery generation, a transient scratch build dir
        # (legacy ``.partial`` or per-generation ``.partial-<gen>``), or
        # unrelated — only the first three are touched here.
        parsed = []          # (entry, entry_path, date_str, suffix_or_None)
        canonical_days = set()
        for entry in entries:
            entry_path = os.path.join(backup_dir, entry)
            if not (os.path.isdir(entry_path) and entry and entry[0].isdigit()):
                continue
            date_str = entry
            suffix = None
            if "." in entry:
                cand, _, _suf = entry.partition(".")
                kind = _backup_sibling_kind(entry, cand)
                if kind is None:
                    # unrelated digit-prefixed dir outside the grammar
                    continue
                date_str, suffix = cand, kind or None
            try:
                dir_time = time.mktime(time.strptime(date_str, "%Y-%m-%d"))
            except (ValueError, OSError):
                # not a date-named folder, or it is busy: leave it alone
                logger.debug("backup cleanup skipped %s", entry_path,
                             exc_info=True)
                continue
            if suffix is None:
                # CORE-007/W2-004: a canonical day counts as a SAFE canonical
                # only when it passes the SAME complete-generation validation
                # a recovery candidate must pass (_COMPLETE marker + valid
                # manifest). An incomplete/corrupt canonical pathname must
                # NOT authorize deletion of the only known-good recovery
                # sibling for that date.
                if _is_valid_complete_generation(entry_path):
                    canonical_days.add(date_str)
                else:
                    logger.info(
                        "portable backup: canonical day %s is not a validated "
                        "complete generation; recovery siblings for it are "
                        "preserved", entry)
            parsed.append((entry, entry_path, date_str, suffix, dir_time))

        for entry, entry_path, date_str, suffix, dir_time in parsed:
            old = (now - dir_time) > max_days * 86400
            if suffix is None:
                # canonical day dir: normal retention
                if old:
                    shutil.rmtree(entry_path, ignore_errors=True)
                continue
            if not old:
                continue
            if suffix == "partial":
                # W2-001/W2-002: a scratch tree may be a complete recovery
                # generation left behind by a publish failure (legacy fixed
                # ``.partial`` or per-generation ``.partial-<gen>``). If valid
                # and the canonical day is missing, preserve it.
                if _is_valid_complete_generation(entry_path) and date_str not in canonical_days:
                    logger.info(
                        "portable backup: kept old complete scratch generation "
                        "%s (canonical day %s missing)", entry, date_str)
                    continue
                # incomplete transient build dir or canonical already exists: bound disk growth
                shutil.rmtree(entry_path, ignore_errors=True)
                continue
            # failed/rollback/recovered: a complete recovery generation. Prune
            # only when a safe canonical generation for the same date exists;
            # if the canonical day is missing this is the ONLY valid backup and
            # must be preserved (or recovered) rather than deleted.
            if date_str in canonical_days:
                shutil.rmtree(entry_path, ignore_errors=True)
            else:
                logger.info(
                    "portable backup: kept old recovery generation %s "
                    "(canonical day %s missing)", entry, date_str)
    except Exception:
        logger.warning("portable backup: cleanup pass failed", exc_info=True)
