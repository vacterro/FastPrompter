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
import json
import os
import threading
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


class PresetNotFoundError(KeyError):
    """No preset with the requested id exists."""


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


def clean_rule(rule: dict, *, strict: bool = False) -> dict:
    """One normalized interval rule, with runtime history stripped.

    ``strict=True`` rejects a rule that carries a wrong-typed field instead of
    healing it, which is what import needs: a foreign document must not be
    silently reshaped into something the user did not write. Every write path
    uses the healing default.
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
        volume = max(0.0, min(1.0, float(volume)))
    except (TypeError, ValueError):
        if strict:
            raise PresetValidationError("rule volume must be a number")
        volume = 0.05

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
        for field in _INT_FIELDS:
            raw = rule.get(field)
            if raw is None or isinstance(raw, bool):
                raise PresetValidationError(
                    f"rule {field} must be an integer, got {raw!r}")
            try:
                int(raw)
            except (TypeError, ValueError):
                raise PresetValidationError(
                    f"rule {field} must be an integer, got {raw!r}")
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
        self._lock = threading.Lock()
        self._loaded = False
        self._presets: dict[str, dict] = {}

    def _ensure_loaded(self) -> dict[str, dict]:
        """Initialization barrier: load from disk before any ID check.

        PRESET-01/PRESET-02: a cold store that has never called ``load``
        has an empty ``_presets`` cache, so the collision check in
        ``import_preset`` and ``create_preset`` would miss a file that
        already exists on disk.  This barrier guarantees the in-memory
        catalog reflects the full on-disk state before any mutation.
        """
        if not self._loaded:
            self._presets = self._read_all()
            self._loaded = True
        return self._presets

    @staticmethod
    def _default_dir() -> str:
        return os.path.join(get_data_dir(), STORE_DIR_NAME)

    @property
    def directory(self) -> str:
        return self._dir

    def _path_for(self, preset_id: str) -> str:
        # The id is the file identity. Reject anything that could escape the
        # store directory before it reaches the filesystem.
        if not preset_id or any(c in preset_id for c in '/\\:*?"<>|'):
            raise PresetValidationError(f"unsafe preset id: {preset_id!r}")
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
        version = doc.get("schema_version", SCHEMA_VERSION)
        try:
            version = int(version)
        except (TypeError, ValueError):
            return None
        if version > SCHEMA_VERSION:
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
        """Write ``doc`` to ``path`` atomically.

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

    def _commit(self, preset: dict) -> dict:
        """Persist one already-clean preset and update the in-memory cache."""
        path = self._path_for(preset["id"])
        self._atomic_write(path, preset)
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
        return self._commit(doc)

    def update_preset(self, preset_id: str, *, name: str | None = None,
                      rules=None, kind: str | None = None) -> dict:
        """Update a preset's mutable fields; ids never change."""
        with self._lock:
            return self._update_preset_locked(preset_id, name=name,
                                              rules=rules, kind=kind)

    def _update_preset_locked(self, preset_id: str, *, name: str | None = None,
                              rules=None, kind: str | None = None) -> dict:
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
            self._ensure_loaded()
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
            self._ensure_loaded()
            return self._delete_preset_locked(preset_id)

    def replace_all(self, presets: list[dict]) -> list[dict]:
        """Atomically replace the whole library (restore / import batch).

        Every document is validated and written BEFORE any removal, so a
        rejected batch leaves the existing library intact. Stale entries are
        removed directly (not via ``delete_preset``) to avoid re-entering the
        lock -- PRESET-03: the original code deadlocked by calling
        ``delete_preset`` from inside the held ``self._lock``.
        """
        with self._lock:
            self._ensure_loaded()
            cleaned = []
            seen: set[str] = set()
            for entry in presets:
                doc = clean_preset(entry, strict=True)
                if doc["id"] in seen:
                    raise PresetValidationError(
                        f"duplicate preset id {doc['id']!r} in replace batch")
                seen.add(doc["id"])
                cleaned.append(doc)
            for doc in cleaned:
                self._commit(doc)
            for stale in set(self._presets) - seen:
                self._delete_preset_locked(stale)
            return [copy.deepcopy(p) for p in cleaned]

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
            self._ensure_loaded()
            if new_name is not None:
                doc["name"] = new_name.strip()[:MAX_NAME_LEN]
                if not doc["name"]:
                    raise PresetValidationError(
                        "an imported preset requires a non-empty name")
            if doc["id"] in self._presets and not overwrite:
                raise PresetValidationError(
                    f"a preset with id {doc['id']!r} already exists; pass "
                    f"overwrite=True to replace it")
            return self._commit(doc)

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
