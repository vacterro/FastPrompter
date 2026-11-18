"""Durable interval-notification preset library (T-1517, Part B).

The timer dialog's presets used to be six hardcoded rule lists inside
``_interval_preset_definitions``: they worked, but a user could not save the
configuration they actually tuned, rename it, duplicate it, or carry it to
another machine. Every save meant "write the rules back into the profile".

This module is the durable half. It owns ONE directory of schema-versioned
JSON documents under ``get_data_dir()/interval_presets/`` and the whole
mutation vocabulary over them (create / read / update / rename / duplicate /
delete / import / export). It is deliberately Qt-free: the timer dialog is one
consumer, a release tool is another, and both need the same truth without a
QApplication in the process.

Contract:

* ONE document per preset file, named ``<preset_id>.json`` -- the id is the
  stable key, the name is a mutable display label;
* every write is ATOMIC (temp file in the same directory, then
  ``os.replace``) so a crash or a full disk can never leave a half-written
  preset behind, and a failed write leaves the previous file byte-identical;
* ``single_rule`` presets carry exactly one rule, ``collection`` presets
  carry an ordered list -- both validated against the same rule schema, and
  the kind is part of the document rather than inferred from the list length;
* import never trusts a foreign document: schema version, kind, rule bounds
  and field types are all checked, and a rejected document raises before any
  byte is published.

Runtime-only fields (``last_fired`` / ``last_fired_minute``) are stripped on
the way in: a preset is a shape, not a firing history.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid

from fastprompter.utils.paths import get_data_dir

#: Schema version of the on-disk document. Bump ONLY for a breaking change;
#: a document from a NEWER version is refused rather than silently downgraded.
SCHEMA_VERSION = 1

#: Preset kinds. ``single_rule`` is one reminder; ``collection`` is an ordered
#: set of them (the 24h Chime shape).
KIND_SINGLE = "single_rule"
KIND_COLLECTION = "collection"
KINDS = (KIND_SINGLE, KIND_COLLECTION)

#: Physical directory name under the data dir.
STORE_DIR_NAME = "interval_presets"

#: Hard bounds, so a corrupt or hostile document can never be unbounded.
MAX_RULES = 64
MAX_NAME_LEN = 120
MAX_SOUND_REF_LEN = 512
MAX_PRESET_BYTES = 512 * 1024

#: The rule fields a preset carries, with their validators. This is the ONE
#: schema both write and import go through.
_INT_FIELDS = {
    "minutes": (1, 60 * 24 * 7),
    "start_minute": (0, 1439),
    "end_minute": (0, 1439),
}
_BOOL_FIELDS = (
    "enabled",
    "show_notification",
    "show_in_top_bar",
    "all_day",
)


class PresetValidationError(ValueError):
    """A preset document or rule failed schema validation."""


class PresetRecoveryError(PresetValidationError):
    """An interrupted batch could not be finished, so a mutation is refused.

    Subclasses ``PresetValidationError`` on purpose: every existing caller
    already handles that type as "this write did not happen, tell the user",
    which is exactly the required behaviour. The distinct name says WHY --
    the library on disk is a mixture of two generations, not that the new
    document was malformed.
    """


class PresetNotFoundError(KeyError):
    """No preset with the requested id exists."""


#: W2-002: the batch journal is ONE fixed path inside the store directory, but
#: ownership of it used to be a per-instance ``threading.Lock``. Two store
#: objects over the same directory (two windows, a window and a release tool)
#: each took their own lock, both believed they owned the transaction, and each
#: replaced the other's journal -- leaving a library that was a MIXTURE of two
#: incompatible ``replace_all`` generations while one writer still reported
#: success. Ownership therefore has to belong to the DIRECTORY, not the object.
#:
#: Two layers, because neither alone is enough:
#:
#: * one process-wide ``RLock`` per resolved directory path, which serializes
#:   store objects in this process and, being re-entrant, cannot deadlock when
#:   one store method calls another on the same directory;
#: * an advisory OS file lock on ``.batch-owner``, which serializes
#:   INDEPENDENT PROCESSES (the preset library can be reached by tools that
#:   never load the GUI).
#:
#: Both are advisory and fail closed by WAITING: the whole transaction runs
#: under them, and the OS lock is released by the kernel if the holder dies, so
#: a killed writer cannot permanently lock the library.
_DIRECTORY_LOCKS: dict[str, threading.RLock] = {}
_DIRECTORY_LOCKS_GUARD = threading.Lock()
#: How long to wait for a foreign process before reporting a conflict. Long
#: enough to cover a legitimately slow batch on a network profile, short enough
#: that a stale lock is surfaced as an error rather than a hang.
_BATCH_LOCK_TIMEOUT = 30.0


def _directory_lock(directory: str) -> threading.RLock:
    """The one in-process lock for ``directory``, created on first use."""
    key = os.path.normcase(os.path.abspath(directory))
    with _DIRECTORY_LOCKS_GUARD:
        lock = _DIRECTORY_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _DIRECTORY_LOCKS[key] = lock
        return lock


class _JournalOwnership:
    """Exclusive ownership of one preset directory's batch transaction.

    Re-entrant at the process level (a nested ``replace_all`` from inside a
    callback must not deadlock) and exclusive across processes via an advisory
    byte-range lock. Acquisition FAILS CLOSED: if the in-process lock or the OS
    lock cannot be taken in time, this raises rather than proceeding with a
    second journal over the same path.

    Nesting reuses the already-held OS lock instead of re-taking it: an
    exclusive file lock is owned per open handle, so a second handle in the SAME
    thread would deadlock against itself. A thread-local set of directories
    already held by this thread is what distinguishes "nested, already mine"
    from "another writer, wait".
    """

    def __init__(self, directory: str) -> None:
        self._directory = directory
        self._key = os.path.normcase(os.path.abspath(directory))
        self._thread_lock = _directory_lock(directory)
        self._fd: int | None = None
        self._nested = False

    def __enter__(self) -> _JournalOwnership:
        self._thread_lock.acquire()
        held = getattr(_HELD_DIRS, "dirs", None)
        if held is None:
            held = set()
            _HELD_DIRS.dirs = held
        if self._key not in held:
            try:
                self._fd = self._acquire_os_lock()
            except BaseException:
                # Never leave the in-process lock held if the OS half failed,
                # or every later store on this directory would hang.
                self._thread_lock.release()
                raise
            held.add(self._key)
        else:
            self._nested = True
        return self

    def __exit__(self, *exc_info) -> None:
        if not self._nested:
            _HELD_DIRS.dirs.discard(self._key)
            if self._fd is not None:
                fd, self._fd = self._fd, None
                _release_os_lock(fd)
        self._thread_lock.release()

    def _acquire_os_lock(self) -> int:
        path = _lock_file_path(self._directory)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
        deadline = time.monotonic() + _BATCH_LOCK_TIMEOUT
        while True:
            try:
                _try_lock_file(fd)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise PresetRecoveryError(
                        "another process is mid-transaction on this preset "
                        "library; refusing to publish a competing batch") \
                        from None
                time.sleep(0.05)


_HELD_DIRS = threading.local()


def _lock_file_path(directory: str) -> str:
    """The OS-lock file for ``directory``, kept OUT of the library directory.

    It deliberately does not live next to the presets: a recovery/reader pass
    enumerates that directory and a stray transaction file there is exactly the
    kind of visible metadata CORE-001/002 exist to avoid, and a rejected batch
    must leave the directory byte-for-byte unchanged. The name is a hash of the
    resolved path, so every process over one library agrees on one lock file.

    Ceiling: two MACHINES sharing a network profile each have their own temp
    dir and therefore their own lock, so cross-machine exclusion is advisory
    only. Single-machine exclusion -- the case SRC-142/W2-002 reproduces -- is
    exact. Upgrade path: place the lock in the library directory and teach the
    reader to ignore it, or add a compare-and-swap on the journal itself.
    """
    import tempfile
    key = hashlib.sha256(
        os.path.normcase(os.path.abspath(directory)).encode("utf-8")).hexdigest()
    return os.path.join(tempfile.gettempdir(), f"fastprompter-presets-{key}.lock")


def _try_lock_file(fd: int) -> None:
    """Take an exclusive, non-blocking OS lock, or raise ``OSError``."""
    if os.name == "nt":
        import msvcrt
        # Lock one byte at the start of the file; blocking=False so a held lock
        # raises instead of hanging, which is what makes the timeout work.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_os_lock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Rule / preset normalization
# ---------------------------------------------------------------------------


def _clean_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1"):
            return True
        if low in ("false", "0"):
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return default


def _clean_int(value, lo: int, hi: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


# CORE-001 (audit/18): an id IS a filename, so the legal-id namespace has to
# match what the reader can see again. ``_path_for`` accepted any string with
# no path separator while ``_read_all`` skipped every name beginning with "."
# as transaction metadata, so ``create_preset('.hidden', ...)`` wrote a
# document that the very next cold load could not find: the preset was
# silently lost, with no error at all. One validator now owns the rule for
# every entry point (create, import, replace_all, internal publication).
_RESERVED_ID_PREFIXES = (".",)
_RESERVED_ID_NAMES = frozenset({".batch-journal", ".batch-staging"})

#: Windows DEVICE names, which the filesystem accepts as a NAME but never as a
#: readable file. ``open("aux.json", "wb")`` succeeds and ``os.replace`` into
#: it reports success, yet ``os.listdir`` never shows it and the next cold load
#: finds nothing -- the same invisible-document data loss CORE-001 is about,
#: reached through a path the dot-prefix rule cannot see. The rule is applied
#: on every platform: a preset created on one OS must still be loadable if the
#: profile directory is later moved to Windows.
_RESERVED_DEVICE_NAMES = frozenset({
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
})

# W2-001: the batch journal is persisted DATA, and a recovery pass reads it to
# decide where to move files. Treating it as trusted instructions let a crafted
# or corrupted journal name ``../outside.json`` as a destination and overwrite a
# writable file outside the preset library, with no validation at all -- the
# normal mutation API validates ids, but recovery bypassed it entirely.
#
# The token is generated as ``uuid.uuid4().hex[:12]`` (see
# ``_stage_and_publish_batch``) and names the staging directory, so it is
# constrained before any path is derived from it. What matters is that it is a
# SINGLE safe path segment: no separator and no dot, so it cannot traverse or
# alias ``.``/``..``. Pinning it to hex would refuse a legitimate journal from a
# different producer (SRC-138/§06 uses non-hex tokens) and strand its staged
# generation, which is the defect this repair exists to prevent -- the narrow
# rule is the traversal ban, not the alphabet.
_BATCH_TOKEN_RE = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")
# A staged file is ``<transfer-id>-<basename>.json``. Recovery moves it, so the
# name must be a SINGLE path segment ending in ``.json`` -- that is the whole
# safety requirement, and it is what keeps a crafted name from retargeting the
# rename. The transfer-id alphabet is deliberately not pinned to the hex this
# build happens to mint: an already-published batch journal written by an older
# or different producer is still a legitimate transaction to finish, and
# refusing it would strand its staged generation (SRC-138/§06). The pairing with
# the validated destination below is what makes the move unambiguous.
_STAGED_NAME_RE = re.compile(r'\A[^/\\:*?"<>|\x00-\x1f]{1,255}\.json\Z')


def _validate_schema_version(raw) -> int:
    """The ONE schema-version rule, shared by import and cold load (W2-004).

    Import (``clean_preset(strict=True)``) already refused version 0, negative
    versions and fractional version numbers, but ``_read_one`` did its own
    ``int(version)``: it rejected only *newer* versions, so a persisted
    ``schema_version = 0`` was accepted and then silently rewritten to 1 by the
    next unrelated edit. ``int(1.5)`` also truncated. Two validators that
    disagree about which documents are readable is the defect; there is now
    one, and both paths call it.

    A missing field is tolerated as the current version: ``SCHEMA_VERSION`` is
    1 and has been since the first release, so a document with no marker can
    only have been written by this build. Refuses a non-exact number and any
    version outside ``1..SCHEMA_VERSION``.
    """
    if raw is None:
        return SCHEMA_VERSION
    # Fractional versions are refused, not truncated: ``int(1.5) == 1`` would
    # reinterpret a document as an older schema it was not written for, which
    # is exactly the lossy coercion this rule exists to stop.
    declared = _strict_int(raw, "preset schema_version")
    if declared > SCHEMA_VERSION:
        raise PresetValidationError(
            f"preset schema_version {declared} is newer than this build "
            f"supports ({SCHEMA_VERSION})")
    if declared < 1:
        raise PresetValidationError(
            f"preset schema_version {declared} is not a known version")
    return declared


def _strict_int(raw, label: str) -> int:
    """Exact integer semantics for strict mode (CORE-006).

    ``int(1.9)`` is 1 and ``int(1.5)`` is 1, so a foreign document could carry
    fractional interval bounds and be "imported" as something the user never
    wrote. Strict mode now refuses any value that is not exactly an integer,
    while still accepting the legacy integer STRING form ("30") that old
    documents legitimately contain.
    """
    if raw is None or isinstance(raw, bool):
        raise PresetValidationError(
            f"{label} must be an integer, got {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if not raw.is_integer():
            raise PresetValidationError(
                f"{label} must be an exact integer, got {raw!r}")
        return int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise PresetValidationError(
                f"{label} must be an integer, got {raw!r}")
        try:
            number = int(text)
        except (TypeError, ValueError):
            raise PresetValidationError(
                f"{label} must be an integer, got {raw!r}")
        # "1.0" is a float spelling, not the legacy integer form; " 30 " is.
        # Compare against the CANONICAL spelling of what was parsed, allowing
        # one leading "+", so the sign is handled symmetrically: the previous
        # ``lstrip("+-")`` accepted "+5" and refused "-5", which is the same
        # spelling class and cannot both be right.
        canonical = text[1:] if text.startswith("+") else text
        if str(number) != canonical:
            raise PresetValidationError(
                f"{label} must be an exact integer, got {raw!r}")
        return number
    raise PresetValidationError(
        f"{label} must be an integer, got {raw!r}")


def validate_preset_id(preset_id: str) -> str:
    """The one decision about whether an id can be a preset file identity.

    Raises :class:`PresetValidationError` for anything the reader would not
    surface, so no write path can create an invisible document.
    """
    if not isinstance(preset_id, str) or not preset_id:
        raise PresetValidationError(
            f"unsafe preset id: {preset_id!r} (must be a non-empty string)")
    if preset_id.strip() != preset_id:
        raise PresetValidationError(
            f"unsafe preset id: {preset_id!r} (surrounding whitespace)")
    if any(char in preset_id for char in '/\\:*?"<>|'):
        raise PresetValidationError(f"unsafe preset id: {preset_id!r}")
    # A control character is not a legal filename character: the write raises
    # OSError (EINVAL) instead of a validation refusal, so a caller that only
    # handles the documented exception would surface a crash rather than a
    # rejected id. Refuse it here, before any filesystem access.
    if any(ord(char) < 32 or ord(char) == 127 for char in preset_id):
        raise PresetValidationError(
            f"unsafe preset id: {preset_id!r} (control character)")
    if preset_id in _RESERVED_ID_NAMES:
        raise PresetValidationError(
            f"preset id {preset_id!r} is transaction metadata, not a preset")
    # A device name is accepted by the filesystem as a name, is never listed,
    # and the write reports success. Reject it before any mutation so a
    # preset cannot be created invisibly (CORE-001).
    if preset_id.split(".")[0].lower() in _RESERVED_DEVICE_NAMES:
        raise PresetValidationError(
            f"preset id {preset_id!r} is a reserved Windows device name and "
            "would not be readable as a document")
    for prefix in _RESERVED_ID_PREFIXES:
        if preset_id.startswith(prefix):
            raise PresetValidationError(
                f"preset id {preset_id!r} begins with {prefix!r} and would be "
                "invisible to the on-disk reader")
    return preset_id


def validate_batch_journal(journal) -> dict:
    """Validate an on-disk batch journal before ANY path is derived from it.

    W2-001: recovery reads destination names straight out of the journal and
    hands them to ``os.path.join``/``os.replace``, so the journal was a trusted
    instruction source even though it is a plain file in the preset directory.
    A journal naming ``../elsewhere/x.json`` (or an absolute path) let a
    recovery pass overwrite a writable file outside the library -- and the
    normal id validator never ran, because recovery derives those paths directly
    instead of going through ``_path_for``.

    The journal is data: every field is checked against the exact shape
    ``_stage_and_publish_batch`` writes. Anything else is refused, which turns a
    crafted or corrupted journal into a visible recovery problem instead of a
    write outside the store.
    """
    if not isinstance(journal, dict):
        raise PresetValidationError("the batch journal must be an object")
    token = journal.get("token")
    if not isinstance(token, str) or not _BATCH_TOKEN_RE.match(token):
        # The token is interpolated into the staging directory name, so a
        # separator or ".." here would retarget the whole batch.
        raise PresetValidationError(
            f"the batch journal carries an invalid token: {token!r}")
    moves = journal.get("moves")
    if not isinstance(moves, list):
        raise PresetValidationError("the batch journal is missing its moves")
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            raise PresetValidationError(
                f"batch journal move {index} is not an object")
        src = move.get("src")
        dst = move.get("dst")
        if not isinstance(src, str) or not _STAGED_NAME_RE.match(src):
            raise PresetValidationError(
                f"batch journal move {index} names an invalid source: {src!r}")
        if not isinstance(dst, str) or not dst.lower().endswith(".json"):
            raise PresetValidationError(
                f"batch journal move {index} names an invalid destination: "
                f"{dst!r}")
        # The destination is a PRESET DOCUMENT NAME, so it must obey the same
        # rule as one -- this is what rejects "..\\x.json", "C:abs.json", an
        # absolute path, and the reserved/device names in one place.
        try:
            validate_preset_id(dst[:-len(".json")])
        except PresetValidationError as exc:
            raise PresetValidationError(
                f"batch journal move {index} names an unsafe destination: "
                f"{exc}") from None
        # A staged file is always "<hex>-<dst>"; recovery only ever moves those.
        # Requiring the match stops a crafted src from pointing the rename at an
        # unrelated file inside the staging directory.
        if not src.endswith(f"-{dst}"):
            raise PresetValidationError(
                f"batch journal move {index} source/destination disagree: "
                f"{src!r} does not stage {dst!r}")
    stale = journal.get("stale", [])
    if not isinstance(stale, list):
        raise PresetValidationError("the batch journal is missing its stale list")
    for stale_id in stale:
        # A stale id is removed through ``_path_for``, which validates; checking
        # here too means the whole journal is refused as one unit before the
        # caller mutates anything.
        validate_preset_id(stale_id)
    return journal


def clean_rule(rule: dict, *, strict: bool = False) -> dict:
    """One normalized interval rule, with runtime history stripped.

    ``strict=True`` rejects a rule that carries a wrong-typed or out-of-range
    field instead of healing it, which is what import needs: a foreign document
    must not be silently reshaped into something the user did not write. Every
    write path uses the healing default.

    CORE-003: range enforcement is part of strictness. Clamping ``minutes``
    from 999999 down to 10080 produced a preset that silently differed from the
    one that was imported, so strict mode now REFUSES an out-of-range number
    rather than quietly rewriting it. Non-finite volumes (NaN/inf) are refused
    for the same reason: they survived ``float()`` and then ``min/max``
    propagated a meaningless value.
    """
    if not isinstance(rule, dict):
        if strict:
            raise PresetValidationError("a rule must be an object")
        return clean_rule({}, strict=False)

    name = rule.get("name", "")
    if not isinstance(name, str):
        if strict:
            raise PresetValidationError("rule name must be a string")
        name = ""
    name = name.strip()

    sound = rule.get("sound", "")
    if not isinstance(sound, str):
        if strict:
            raise PresetValidationError("rule sound must be a string")
        sound = ""
    sound = sound.strip()
    if len(sound) > MAX_SOUND_REF_LEN:
        if strict:
            raise PresetValidationError("rule sound reference is too long")
        sound = sound[:MAX_SOUND_REF_LEN]

    volume = rule.get("volume", 0.05)
    if isinstance(volume, bool) or not isinstance(volume, (int, float, str)):
        if strict:
            raise PresetValidationError("rule volume must be a number")
        volume = 0.05
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        if strict:
            raise PresetValidationError("rule volume must be a number")
        volume = 0.05
    else:
        if not math.isfinite(volume):
            if strict:
                raise PresetValidationError(
                    f"rule volume must be finite, got {volume!r}")
            volume = 0.05
        if strict and not (0.0 <= volume <= 1.0):
            raise PresetValidationError(
                f"rule volume must be between 0 and 1, got {volume!r}")
        volume = max(0.0, min(1.0, volume))

    align_mode = rule.get("align_mode", "clock")
    if not isinstance(align_mode, str):
        if strict:
            raise PresetValidationError("rule align_mode must be a string")
        align_mode = "clock"
    align_mode = align_mode.strip().lower()
    if align_mode not in ("clock", "elapsed"):
        if strict:
            raise PresetValidationError(
                f"rule align_mode must be clock or elapsed, got {align_mode!r}")
        align_mode = "clock"

    clean = {
        "name": name,
        "minutes": _clean_int(rule.get("minutes", 60),
                              *_INT_FIELDS["minutes"], 60),
        "enabled": _clean_bool(rule.get("enabled", True), True),
        "sound": sound,
        "volume": volume,
        "show_notification": _clean_bool(
            rule.get("show_notification", True), True),
        "show_in_top_bar": _clean_bool(
            rule.get("show_in_top_bar", False), False),
        "align_mode": align_mode,
        "all_day": _clean_bool(rule.get("all_day", True), True),
        "start_minute": _clean_int(rule.get("start_minute", 0),
                                   *_INT_FIELDS["start_minute"], 0),
        "end_minute": _clean_int(rule.get("end_minute", 1439),
                                 *_INT_FIELDS["end_minute"], 1439),
    }

    if strict:
        for field, (lo, hi) in _INT_FIELDS.items():
            number = _strict_int(rule.get(field), f"rule {field}")
            # CORE-003: reject, never clamp, an out-of-range imported value.
            if not (lo <= number <= hi):
                raise PresetValidationError(
                    f"rule {field} must be between {lo} and {hi}, got {number!r}")
            clean[field] = number
        for field in _BOOL_FIELDS:
            raw = rule.get(field, None)
            if raw is not None and not isinstance(raw, bool):
                # Legacy documents may carry the string "True"/"False"; a real
                # bool is accepted directly. Anything else is a foreign shape.
                if not (isinstance(raw, str)
                        and raw.strip().lower() in ("true", "false")):
                    raise PresetValidationError(
                        f"rule {field} must be a boolean, got {raw!r}")

    return clean


def _rule_id(rule: dict) -> str:
    """A rule's logical id, preserved when present, minted when absent."""
    rid = rule.get("id") if isinstance(rule, dict) else None
    if isinstance(rid, str) and rid.strip():
        return rid.strip()
    return uuid.uuid4().hex[:12]


def clean_rules(rules, *, strict: bool = False) -> list[dict]:
    """Normalize a list of rules, minting ids for entries that lack one."""
    if not isinstance(rules, list):
        if strict:
            raise PresetValidationError("rules must be a list")
        return []
    if strict and len(rules) > MAX_RULES:
        raise PresetValidationError(
            f"a preset may carry at most {MAX_RULES} rules")
    out: list[dict] = []
    seen: set[str] = set()
    for entry in rules:
        clean = clean_rule(entry if isinstance(entry, dict) else {},
                           strict=strict)
        rid = _rule_id(entry if isinstance(entry, dict) else {})
        if rid in seen:
            if strict:
                raise PresetValidationError(f"duplicate rule id {rid!r}")
            rid = uuid.uuid4().hex[:12]
        seen.add(rid)
        clean["id"] = rid
        out.append(clean)
    return out


def clean_preset(preset: dict, *, strict: bool = False) -> dict:
    """The canonical stored shape of one preset document.

    ``kind`` decides whether ``rules`` is a single-rule list or a collection;
    the document always stores a LIST so consumers never branch on shape.
    """
    if not isinstance(preset, dict):
        if strict:
            raise PresetValidationError("a preset must be an object")
        return clean_preset({}, strict=False)

    name = preset.get("name", "")
    if not isinstance(name, str):
        if strict:
            raise PresetValidationError("preset name must be a string")
        name = ""
    name = name.strip()
    if len(name) > MAX_NAME_LEN:
        if strict:
            raise PresetValidationError("preset name is too long")
        name = name[:MAX_NAME_LEN]

    # CORE-003: validate the declared schema BEFORE normalizing anything. The
    # old code never looked at the field at all and always stamped
    # SCHEMA_VERSION on the result, so a document declaring version 9999 was
    # accepted and silently rewritten as version 1 -- a future document
    # misinterpreted as an older one. Strict mode refuses any version it does
    # not know how to read; healing mode keeps the historical behaviour of
    # tolerating a missing or unreadable marker.
    raw_version = preset.get("schema_version", None)
    if strict:
        _validate_schema_version(raw_version)

    kind = preset.get("kind", KIND_SINGLE)
    if not isinstance(kind, str):
        if strict:
            raise PresetValidationError("preset kind must be a string")
        kind = KIND_SINGLE
    kind = kind.strip().lower()
    if kind not in KINDS:
        if strict:
            raise PresetValidationError(
                f"preset kind must be one of {KINDS}, got {kind!r}")
        kind = KIND_SINGLE

    raw_rules = preset.get("rules")
    if raw_rules is None:
        # Tolerate a single-rule document that carried the rule inline.
        inline = preset.get("rule")
        raw_rules = [inline] if isinstance(inline, dict) else []
    rules = clean_rules(raw_rules, strict=strict)

    if strict:
        if not name:
            raise PresetValidationError("preset name must not be empty")
        if kind == KIND_SINGLE and len(rules) != 1:
            raise PresetValidationError(
                "a single_rule preset must carry exactly one rule")
        if kind == KIND_COLLECTION and not rules:
            raise PresetValidationError(
                "a collection preset must carry at least one rule")

    preset_id = preset.get("id", "")
    if preset_id is None:
        preset_id = ""
    if not isinstance(preset_id, str):
        if strict:
            raise PresetValidationError("preset id must be a string")
        preset_id = ""
    preset_id = preset_id.strip()
    if preset_id:
        # CORE-001: the same namespace rule applies to every document that
        # reaches the store, whether it was created or imported.
        validate_preset_id(preset_id)

    return {
        "schema_version": SCHEMA_VERSION,
        "id": preset_id or uuid.uuid4().hex[:12],
        "name": name,
        "kind": kind,
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class IntervalPresetStore:
    """Durable interval-preset library under ``get_data_dir()``.

    The directory is created lazily on first use, never at import time: a
    headless release tool that only reads must not require a writable data
    directory to import this module.

    ``directory`` may be passed explicitly (tests, tools); the default is
    ``<data>/interval_presets/``.
    """

    def __init__(self, directory: str | None = None) -> None:
        self._dir = directory if directory is not None else self._default_dir()
        # W2-002: the lock belongs to the DIRECTORY, not to this object. Two
        # stores over one directory (the timer dialog and a release tool) must
        # contend for the same lock, or each believes it is the only writer.
        self._lock = _directory_lock(self._dir)
        self._loaded = False
        self._presets: dict[str, dict] = {}
        self._recovery_problem: str | None = None

    def _ensure_loaded(self) -> dict[str, dict]:
        """Initialization barrier: load from disk before any ID check.

        PRESET-01/PRESET-02: a cold store that has never called ``load``
        has an empty ``_presets`` cache, so the collision check in
        ``import_preset`` and ``create_preset`` would miss a file that
        already exists on disk.  This barrier guarantees the in-memory
        catalog reflects the full on-disk state before any mutation.

        SRC-138/R07: a WARM cache is not proof that a path is absent. Two
        store instances over one directory (the timer dialog and a release
        tool, or two windows) each load once and then disagree about what
        exists; the stale one used to import straight over the other's
        document with ``overwrite=False``. Every MUTATION therefore refreshes
        through ``_refresh_for_mutation`` instead of trusting ``_loaded``.
        """
        if not self._loaded:
            # CORE-002: an interrupted replace_all leaves a journal behind;
            # finishing it here means the catalog is never read half-migrated.
            self._recover_pending_batch()
            self._presets = self._read_all()
            self._loaded = True
        return self._presets

    def _refresh_for_mutation(self) -> dict[str, dict]:
        """Re-read the directory before deciding that an id is free.

        A cached listing answers "was this here when I loaded", which is not
        the question a create or a no-overwrite import asks. Reads keep using
        the cheap cache; only the write path pays for a fresh listing.

        SRC-138/R05: an unresolved transaction is a refusal, not a warning.
        Writing a new preset on top of a mixture means the user's next batch
        would silently promote the mixture to a permanent generation; the
        journal is the only record that the library needs finishing first.
        """
        self._recover_pending_batch()
        self._refuse_if_unrecovered()
        self._presets = self._read_all()
        self._loaded = True
        return self._presets

    def _refuse_if_unrecovered(self) -> None:
        if not self._recovery_problem:
            return
        raise PresetRecoveryError(
            f"{self._recovery_problem}; refusing to change the library until "
            "it is finished or restored")

    @staticmethod
    def _default_dir() -> str:
        return os.path.join(get_data_dir(), STORE_DIR_NAME)

    @property
    def directory(self) -> str:
        return self._dir

    def _path_for(self, preset_id: str) -> str:
        # The id is the file identity, so the ONE validator decides what may
        # become a filename -- including the reserved/reader-invisible names
        # that CORE-001 showed could be written and then lost.
        validate_preset_id(preset_id)
        return os.path.join(self._dir, f"{preset_id}.json")

    # -- load / save --------------------------------------------------------

    def _ensure_dir(self) -> None:
        os.makedirs(self._dir, exist_ok=True)

    def load(self, *, force: bool = False) -> list[dict]:
        """Every stored preset, in a stable (name, id) order.

        A corrupt document is skipped, never fatal: one bad file must not
        make the whole library unreadable. ``force=True`` re-reads from disk.
        """
        with self._lock:
            if not self._loaded or force:
                self._recover_pending_batch()
                self._presets = self._read_all()
                self._loaded = True
            return [copy.deepcopy(p) for p in self._ordered()]

    def _read_all(self) -> dict[str, dict]:
        try:
            names = os.listdir(self._dir)
        except OSError:
            return {}
        out: dict[str, dict] = {}
        for name in sorted(names):
            if name.startswith("."):
                # The batch journal and staging directories are transaction
                # metadata, never preset documents (CORE-002).
                continue
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(self._dir, name)
            preset = self._read_one(path)
            if preset is None:
                continue
            out[preset["id"]] = preset
        return out

    def _read_one(self, path: str) -> dict | None:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_PRESET_BYTES + 1)
        except OSError:
            return None
        if len(raw) > MAX_PRESET_BYTES:
            return None
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        # W2-004: cold load used its own lossy ``int(version)`` and rejected
        # only NEWER versions, so ``schema_version = 0`` (or 1.5) was accepted
        # and then silently rewritten to 1 by the next unrelated edit -- losing
        # the original version identity. The load path now applies the SAME rule
        # as import. A document this build cannot read is SKIPPED, not repaired:
        # its bytes stay on disk untouched for diagnosis or a newer build, which
        # is requirement 6.
        try:
            _validate_schema_version(doc.get("schema_version", None))
        except PresetValidationError:
            return None
        try:
            preset = clean_preset(doc, strict=False)
        except PresetValidationError:
            return None
        # The file name is the identity; a document whose id disagrees is
        # corrupt (or hand-edited) and is skipped rather than re-keyed.
        stem = os.path.splitext(os.path.basename(path))[0]
        if preset["id"] != stem:
            return None
        return preset

    def _ordered(self) -> list[dict]:
        return sorted(self._presets.values(),
                      key=lambda p: (p["name"].lower(), p["id"]))

    def _atomic_write(self, path: str, doc: dict) -> None:
        """Write ``doc`` to ``path`` atomically, replacing any existing file.

        The temp file is created in the SAME directory (so the replace is a
        rename on one filesystem, never a copy that can half-land), the
        payload is fully serialized BEFORE anything touches disk, and any
        failure removes the temp file and leaves the previous document
        byte-identical.
        """
        payload = json.dumps(doc, indent=2, ensure_ascii=False,
                             sort_keys=True).encode("utf-8")
        if len(payload) > MAX_PRESET_BYTES:
            raise PresetValidationError("preset document is too large")
        self._ensure_dir()
        # The temp file lives in the SAME directory as the target, so the
        # publish is a rename on one filesystem: an atomic replace, never a
        # cross-device copy that can land half-written.
        tmp_path = f"{path}.tmp-{uuid.uuid4().hex[:8]}"
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _publish_new(self, path: str, doc: dict) -> None:
        """Create ``path`` with ``doc``, failing if it already exists.

        SRC-138/R07: the refusal must be decided by the FILESYSTEM, not by a
        listing taken moments earlier -- another instance or process can
        create the document between the check and the write. ``O_EXCL`` makes
        the create itself the decision, so there is no window to lose.

        This path only ever CREATES, so a failure part-way through removes the
        file it just created and leaves the directory exactly as it was. An
        existing document is never opened for writing here at all.
        """
        payload = json.dumps(doc, indent=2, ensure_ascii=False,
                             sort_keys=True).encode("utf-8")
        if len(payload) > MAX_PRESET_BYTES:
            raise PresetValidationError("preset document is too large")
        self._ensure_dir()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags)
        except FileExistsError:
            raise PresetValidationError(
                f"a preset with id {doc['id']!r} already exists") from None
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                os.remove(path)
            except OSError:
                pass
            raise

    def _commit(self, preset: dict, *, overwrite: bool = True) -> dict:
        """Persist one already-clean preset and update the in-memory cache.

        ``overwrite=False`` is the create path: the write itself refuses a
        colliding id instead of trusting an earlier existence check.
        """
        path = self._path_for(preset["id"])
        if overwrite:
            self._atomic_write(path, preset)
        else:
            self._publish_new(path, preset)
        self._presets[preset["id"]] = copy.deepcopy(preset)
        self._loaded = True
        return copy.deepcopy(preset)

    # -- queries ------------------------------------------------------------

    def get(self, preset_id: str) -> dict | None:
        with self._lock:
            self._ensure_loaded()
            preset = self._presets.get(preset_id)
            return copy.deepcopy(preset) if preset else None

    def count(self) -> int:
        return len(self.load())

    def exists(self, preset_id: str) -> bool:
        return self.get(preset_id) is not None

    # -- mutations ----------------------------------------------------------

    def create_preset(self, name: str, rules, kind: str = KIND_SINGLE,
                      preset_id: str | None = None) -> dict:
        """Create and persist a new preset; returns the stored document.

        ``preset_id`` lets a caller mint the id (an import reusing the
        source id); otherwise a fresh one is generated. A name collision is
        allowed -- ids, not names, are the identity.
        """
        with self._lock:
            self._refresh_for_mutation()
            return self._create_preset_locked(name, rules, kind, preset_id)

    def _create_preset_locked(self, name: str, rules,
                              kind: str = KIND_SINGLE,
                              preset_id: str | None = None) -> dict:
        doc = clean_preset({
            "id": preset_id,
            "name": name,
            "kind": kind,
            "rules": rules,
        }, strict=True)
        self._ensure_loaded()
        if doc["id"] in self._presets:
            raise PresetValidationError(
                f"a preset with id {doc['id']!r} already exists")
        # SRC-138/R07: the cache check above is a fast, friendly refusal; the
        # O_EXCL create below is what actually guarantees no clobber.
        return self._commit(doc, overwrite=False)

    def update_preset(self, preset_id: str, *, name: str | None = None,
                      rules=None, kind: str | None = None) -> dict:
        """Update a preset's mutable fields; ids never change."""
        with self._lock:
            return self._update_preset_locked(preset_id, name=name,
                                              rules=rules, kind=kind)

    def _update_preset_locked(self, preset_id: str, *, name: str | None = None,
                              rules=None, kind: str | None = None) -> dict:
        self._refresh_for_mutation()
        current = self._require(preset_id)
        merged = copy.deepcopy(current)
        if name is not None:
            merged["name"] = name
        if rules is not None:
            merged["rules"] = rules
        if kind is not None:
            merged["kind"] = kind
        doc = clean_preset(merged, strict=True)
        doc["id"] = preset_id
        return self._commit(doc)

    def rename_preset(self, preset_id: str, new_name: str) -> dict:
        """Names are mutable display labels; ids never change."""
        with self._lock:
            self._ensure_loaded()
            self._require(preset_id)
            return self._update_preset_locked(preset_id, name=new_name)

    def duplicate_preset(self, preset_id: str, *,
                         new_name: str | None = None) -> dict:
        """A deep copy under a fresh id (the original is untouched)."""
        with self._lock:
            self._refresh_for_mutation()
            current = self._require(preset_id)
            rules = copy.deepcopy(current["rules"])
            for rule in rules:
                # A duplicated reminder is a NEW reminder: keeping the source
                # rule id would make two presets claim the same logical rule.
                rule["id"] = uuid.uuid4().hex[:12]
            base = current["name"]
            name = new_name or _next_copy_name(
                base, {p["name"] for p in self._presets.values()})
            return self._create_preset_locked(name, rules, current["kind"])

    def delete_preset(self, preset_id: str) -> bool:
        """Remove one preset. Deleting an absent preset is a no-op False."""
        with self._lock:
            self._refresh_for_mutation()
            return self._delete_preset_locked(preset_id)

    def replace_all(self, presets: list[dict]) -> list[dict]:
        """Replace the whole library as ONE recoverable generation.

        Every document is validated before any byte is written, so a rejected
        batch leaves the existing library intact.

        CORE-002: per-file atomicity was not batch atomicity. The previous code
        committed each document in turn and then deleted stale entries, so an
        ``OSError`` on the second write left the library as a MIXED generation
        -- neither the old set nor the requested one, with no way to finish or
        roll back. The replacement now runs as a journaled transaction:

        1. stage the complete new generation in a private staging directory
           (nothing in the active catalog is touched yet),
        2. write a durable journal naming the batch,
        3. move the staged files into place,
        4. delete stale files,
        5. remove the journal.

        If the process dies between (2) and (5), ``_recover_pending_batch``
        finishes the move on the next load, so a reload converges on the
        complete NEW generation. SRC-138/R06: that is a RECOVERY guarantee,
        not atomic visibility -- see ``_apply_batch_journal``. An interrupted
        batch is reported as interrupted; it never claims the old library is
        still intact.

        PRESET-03 is preserved: stale removal uses ``_delete_preset_locked``
        rather than ``delete_preset`` so the held lock is never re-entered.
        """
        with self._lock:
            # W2-002 item 3-4: ownership spans the WHOLE transaction -- recovery
            # check, catalog refresh, staging, journal publication, replacement,
            # stale deletion and journal retirement -- and it is held by the
            # DIRECTORY, so no second store (in this process or another) can
            # replace the shared journal mid-batch. The refresh below runs under
            # that ownership, so the recovery check cannot observe one writer's
            # half-finished generation as if it were the settled library.
            with _JournalOwnership(self._dir):
                return self._replace_all_owned(presets)

    def _replace_all_owned(self, presets: list[dict]) -> list[dict]:
        self._refresh_for_mutation()
        cleaned: list[dict] = []
        seen: set[str] = set()
        for entry in presets:
            doc = clean_preset(entry, strict=True)
            # Reject an unsafe id BEFORE it can name a path.
            self._path_for(doc["id"])
            if doc["id"] in seen:
                raise PresetValidationError(
                    f"duplicate preset id {doc['id']!r} in replace batch")
            seen.add(doc["id"])
            cleaned.append(doc)

        try:
            self._stage_and_publish_batch(cleaned, seen)
        except BaseException:
            # The on-disk generation is NOT known to be untouched: the
            # moves are per-file atomic, so an interruption can leave a
            # mixture that the retained journal will finish. Refreshing
            # the cache from disk reports what is actually there instead
            # of restoring a snapshot that no longer matches the files.
            self._loaded = False
            self._ensure_loaded()
            raise
        self._presets = {doc["id"]: copy.deepcopy(doc) for doc in cleaned}
        self._loaded = True
        return [copy.deepcopy(doc) for doc in cleaned]

    def _batch_journal_path(self) -> str:
        return os.path.join(self._dir, ".batch-journal.json")

    def _stage_and_publish_batch(self, cleaned: list[dict],
                                 keep: set[str]) -> None:
        """Stage the whole generation, then publish it under one journal.

        Staging happens in ``.batch-staging-<token>`` INSIDE the store
        directory so every publish is a same-filesystem rename. The journal
        lists the (staged file, final name) moves plus the stale ids to delete;
        it is the only thing a recovery pass needs.
        """
        import shutil

        self._ensure_dir()
        token = uuid.uuid4().hex[:12]
        staging_dir = os.path.join(self._dir, f".batch-staging-{token}")
        os.makedirs(staging_dir, exist_ok=True)
        staged: list[tuple[str, str, str]] = []
        try:
            for doc in cleaned:
                final = self._path_for(doc["id"])
                name = os.path.basename(final)
                tmp = os.path.join(staging_dir, f"{uuid.uuid4().hex[:8]}-{name}")
                payload = json.dumps(doc, indent=2, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")
                if len(payload) > MAX_PRESET_BYTES:
                    raise PresetValidationError("preset document is too large")
                with open(tmp, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged.append((tmp, name, hashlib.sha256(payload).hexdigest()))

            stale = sorted(set(self._presets) - keep)
            # The digest is what makes recovery able to tell "already published"
            # from "never published": without it, an old document still sitting
            # at the destination looks exactly like a completed move.
            journal = {
                "token": token,
                "moves": [{"src": os.path.basename(src), "dst": dst,
                           "sha256": digest}
                          for src, dst, digest in staged],
                "stale": stale,
            }
            journal_path = self._batch_journal_path()
            journal_tmp = f"{journal_path}.{token}.tmp"
            with open(journal_tmp, "wb") as handle:
                handle.write(json.dumps(journal, ensure_ascii=False).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(journal_tmp, journal_path)

            stale_failed: dict = {}
            if not self._apply_batch_journal(journal_path, staging_dir,
                                             stale_failed):
                if "at" in stale_failed and self._apply_batch_journal(
                        journal_path, staging_dir):
                    # The new generation was already published; only the
                    # deletion of a superseded document failed and the retry
                    # succeeded. That is a completed batch, not an interruption.
                    pass
                else:
                    # The journal is retained, so the NEXT load finishes it --
                    # but the files on disk may already be a mixture, so the
                    # refusal must say so instead of claiming the previous
                    # library is untouched.
                    raise PresetValidationError(
                        "preset batch was interrupted before it completed; the "
                        "staged generation is retained and the next load will "
                        "finish it")
        finally:
            # CORE-002: the staging directory is the ONLY recovery source, so
            # it is removed only once the journal is gone (i.e. the batch
            # actually committed). If publication stopped early the journal and
            # the remaining staged files stay on disk for _recover_pending_batch
            # to finish on the next load; deleting them here would strand an
            # unrecoverable half-batch.
            if not os.path.exists(self._batch_journal_path()):
                try:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                except Exception:
                    pass

    def _apply_batch_journal(self, journal_path: str, staging_dir: str,
                             stale_failed: dict | None = None) -> bool:
        """Complete one staged batch: move files in, delete stale, drop journal.

        Idempotent: a file already moved is simply absent from staging, and a
        stale file already deleted is simply gone. Running this twice -- once
        live, once from recovery after a crash -- converges on the same result.

        SRC-138/R06: THE GUARANTEE IS RECOVERY, NOT ATOMIC VISIBILITY.
        ``os.replace`` is per-file atomic; a sequence of them is not one
        transaction. A reader listing the directory mid-loop can observe a
        MIXED generation, and a process killed between two moves leaves one on
        disk. What IS guaranteed: the mixture is always repairable and never
        silently accepted, because the journal names every remaining move and
        the next load finishes the batch, converging on the complete NEW
        generation.

        True atomic visibility would need an immutable generation directory
        plus one active-generation pointer, which this library deliberately
        does not carry. The contract is therefore stated where it is enforced
        and an interrupted batch reports itself as INTERRUPTED, never as
        "the previous library is unchanged".

        SRC-138/§06 K: "the destination exists" is NOT proof that this move
        happened. The old generation occupies the same path, so a batch whose
        staged file vanished would have accepted the OLD document as a
        completed move and then deleted it as stale -- wiping the library.
        The journal records each new document's digest, and a destination only
        counts as published when its bytes match. Anything else stops the
        batch before the destructive half.

        Returns True when the batch committed, False when it stopped early and
        the journal was retained for recovery. ``stale_failed`` (an out-param
        dict) is filled with the id whose deletion raised, so the caller can
        distinguish "a move died" from "only the destructive half died".
        """
        with open(journal_path, "rb") as handle:
            journal = json.loads(handle.read().decode("utf-8"))
        # W2-001: every destination below is derived from this file. Validate
        # BEFORE the first path is built, so a crafted/corrupt journal can only
        # ever produce a refusal, never a rename outside the library.
        validate_batch_journal(journal)
        moves = journal.get("moves", ())
        try:
            for move in moves:
                src = os.path.join(staging_dir, move["src"])
                dst = os.path.join(self._dir, move["dst"])
                expected = move.get("sha256")
                if os.path.exists(src):
                    os.replace(src, dst)
                elif expected is None:
                    # A journal from before digests were recorded. Recovery of
                    # an old journal must still work; existence is all it can
                    # offer, so it is accepted for those only.
                    if not os.path.exists(dst):
                        return False
                elif _file_sha256(dst) != expected:
                    # Neither the staged copy nor a published copy with the
                    # batch's own bytes: do NOT advance to the destructive half.
                    return False
        except OSError:
            # A transient filesystem error must not become permanent data
            # loss: the journal is still on disk and recovery can finish it.
            return False
        try:
            for preset_id in journal.get("stale", ()):
                path = self._path_for(preset_id)
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        except OSError:
            # The new generation is fully published, so this is the destructive
            # half failing -- NOT a half-published batch. Retrying the deletion
            # is safe and is what the caller does; if it keeps failing the
            # journal stays for the next load.
            if stale_failed is not None:
                stale_failed["at"] = preset_id
            return False
        os.remove(journal_path)
        return True

    def _recover_pending_batch(self) -> None:
        """Finish or discard an interrupted batch before reading the catalog.

        Called from ``_ensure_loaded``/``load``. Any exception is swallowed by
        the caller's normal file-skips: recovery must never make the library
        unreadable, and a second attempt on the next load is safe.

        SRC-138/R05: swallowing the failure is right, staying SILENT about it
        is not. A journal that cannot be applied leaves the directory as a
        mixture of two generations, and the catalog then reports that mixture
        as if it were a library the user built. ``recovery_problem`` records
        the unresolved state for callers that can surface it, and conflicting
        mutations are refused by ``_refuse_if_unrecovered``.
        """
        journal_path = self._batch_journal_path()
        if not os.path.exists(journal_path):
            self._recovery_problem = None
            return
        try:
            with open(journal_path, "rb") as handle:
                journal = json.loads(handle.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            # A journal we cannot even parse is an incomplete transaction we
            # cannot finish. It is NOT deleted: the staged generation may still
            # be the only copy of the new documents.
            self._recovery_problem = (
                f"the preset batch journal is unreadable ({exc.__class__.__name__}); "
                "the library may be a mixture of two generations")
            return
        if not isinstance(journal, dict):
            self._recovery_problem = (
                "the preset batch journal is not an object; the library may be "
                "a mixture of two generations")
            return
        # W2-001: the staging directory is derived from the journal token and is
        # later removed recursively, so the token must be proven safe BEFORE it
        # becomes a path. A journal that fails validation is an unreadable
        # transaction, handled exactly like a parse failure: kept, reported,
        # never acted on.
        try:
            validate_batch_journal(journal)
        except PresetValidationError as exc:
            self._recovery_problem = (
                f"the preset batch journal failed validation ({exc}); the "
                "library may be a mixture of two generations")
            return
        staging_dir = os.path.join(
            self._dir, f".batch-staging-{journal.get('token', '')}")
        # W2-002: finishing another writer's batch is itself a transaction on
        # this directory, so it must own the journal while it does it. A foreign
        # process that is mid-batch is waited for, never raced; if it cannot be
        # taken, the journal is LEFT IN PLACE and reported, which is the same
        # thing recovery does after any other failure.
        try:
            ownership = _JournalOwnership(self._dir)
            ownership.__enter__()
        except PresetRecoveryError as exc:
            self._recovery_problem = str(exc)
            return
        except OSError as exc:
            self._recovery_problem = (
                f"could not take ownership of the preset library "
                f"({exc.__class__.__name__}); the library may be a mixture of "
                "two generations")
            return
        try:
            done = self._apply_batch_journal(journal_path, staging_dir)
        except Exception as exc:
            self._recovery_problem = (
                f"finishing the interrupted preset batch failed "
                f"({exc.__class__.__name__}); the library may be a mixture of "
                "two generations")
            return
        finally:
            ownership.__exit__(None, None, None)
        if not done:
            self._recovery_problem = (
                "an interrupted preset batch could not be finished; the "
                "library may be a mixture of two generations")
        else:
            # The batch committed, so the staging directory is now dead weight.
            self._discard_staging(staging_dir)

    def _discard_staging(self, staging_dir: str) -> None:
        """Remove a staging directory whose batch has already committed."""
        import shutil
        try:
            shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass

    @property
    def recovery_problem(self) -> str | None:
        """Set when an interrupted batch could not be finished.

        ``None`` means the catalog on disk is a complete generation. A string
        is the truthful description of an unresolved transaction, so a caller
        can tell the user instead of presenting a mixture as their library.
        """
        return self._recovery_problem

    def _delete_preset_locked(self, preset_id: str) -> bool:
        """Delete one preset without re-acquiring the lock (caller holds it)."""
        path = self._path_for(preset_id)
        try:
            os.remove(path)
        except FileNotFoundError:
            self._presets.pop(preset_id, None)
            return False
        except OSError:
            raise
        self._presets.pop(preset_id, None)
        return True

    def _require(self, preset_id: str) -> dict:
        self._ensure_loaded()
        preset = self._presets.get(preset_id)
        if preset is None:
            raise PresetNotFoundError(preset_id)
        return preset

    # -- import / export ----------------------------------------------------

    def export_preset(self, preset_id: str) -> dict:
        """A portable copy of one preset (a private deepcopy)."""
        with self._lock:
            preset = self._require(preset_id)
            return copy.deepcopy(preset)

    def export_all(self) -> list[dict]:
        """Portable copies of every stored preset."""
        return self.load()

    def import_preset(self, document: dict, *,
                      new_name: str | None = None,
                      overwrite: bool = False) -> dict:
        """Import ONE foreign document into the store.

        ``new_name`` imports under a different label (importing the same
        preset twice under distinct names). ``overwrite=True`` replaces an
        existing document with the same id; without it a colliding id is a
        refusal rather than a silent overwrite.

        The document is validated BEFORE any byte is written: a rejected
        import leaves the store byte-identical.
        """
        with self._lock:
            doc = clean_preset(document, strict=True)
            self._refresh_for_mutation()
            if new_name is not None:
                doc["name"] = new_name.strip()[:MAX_NAME_LEN]
                if not doc["name"]:
                    raise PresetValidationError(
                        "an imported preset requires a non-empty name")
            if doc["id"] in self._presets and not overwrite:
                raise PresetValidationError(
                    f"a preset with id {doc['id']!r} already exists; pass "
                    f"overwrite=True to replace it")
            # SRC-138/R07: `overwrite=False` is a CREATE, so the atomic
            # create-if-absent write enforces it even if another instance
            # created the id after the listing above.
            return self._commit(doc, overwrite=overwrite)

    def import_document_bytes(self, payload: bytes, **kwargs) -> dict:
        """Import from raw JSON bytes (a file the user picked)."""
        if len(payload) > MAX_PRESET_BYTES:
            raise PresetValidationError("preset document is too large")
        try:
            doc = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PresetValidationError(
                f"preset document is not valid JSON: {exc}") from exc
        return self.import_preset(doc, **kwargs)


def _file_sha256(path: str) -> str | None:
    """Digest of a file's bytes, or ``None`` when it cannot be read."""
    import hashlib
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def _next_copy_name(base: str, taken: set[str]) -> str:
    """``Base`` -> ``Base (copy)`` -> ``Base (copy 2)``, skipping collisions."""
    candidate = f"{base} (copy)"
    if candidate not in taken:
        return candidate
    n = 2
    while f"{base} (copy {n})" in taken:
        n += 1
    return f"{base} (copy {n})"


def default_store() -> IntervalPresetStore:
    """The process-wide store bound to the real data directory."""
    return IntervalPresetStore()
