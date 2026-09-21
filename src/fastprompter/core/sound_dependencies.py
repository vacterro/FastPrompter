"""W2-004 / CORE-004 (audit/10): one read-only dependency enumerator for a
managed ``user:`` sound reference.

Managed-library files live outside any single profile database, but deletion
surfaces used to know only about a LOCAL subset of consumers: the Problip
dialog scanned the current pool + current profile events, the Audio Hub scanned
only current-profile events. A managed WAV can also be referenced by saved
presets (application-global ``audio.db``) and by saved ambience rules
(application-global ``ambience.db``), so a Remove could silently leave those
pointing at a vanished file while the confirmation text implied it was safe.

This module owns the ONE enumerator both deletion surfaces call. It returns
TYPED consumers (not pre-formatted UI strings) so each dialog can render
truthful localized text, and it distinguishes "no references" from "a required
store could not be inspected" -- the latter is ``impact_unknown`` and must be
treated as unsafe, never as empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastprompter.core import sound_library


@dataclass
class Dependencies:
    """Every known consumer of one managed ``user:`` ref."""

    ref: str
    #: Problip pool membership (application-global ProblipStore).
    problip_pool: bool = False
    #: Active profile event keys whose mapping equals this ref.
    events: list[str] = field(default_factory=list)
    #: Saved preset ids carrying this ref in one of their event mappings.
    presets: list[str] = field(default_factory=list)
    #: Saved ambience rule ids carrying this ref as their ``sound_ref``.
    ambience_rules: list[str] = field(default_factory=list)
    #: Stores that could not be inspected. Non-empty means the impact set is
    #: NOT known and must be treated as unsafe.
    impact_unknown: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.problip_pool or self.events or self.presets
                    or self.ambience_rules)

    def is_unknown(self) -> bool:
        return bool(self.impact_unknown)


def _preset_store_dependencies(ref: str, deps: Dependencies) -> None:
    try:
        from fastprompter.core.sound_presets import PresetStore

        store = PresetStore()
        for preset in store.list_presets(include_hidden=True):
            for entry in (preset.get("events") or {}).values():
                if isinstance(entry, dict) and entry.get("file") == ref:
                    deps.presets.append(str(preset.get("id") or ""))
                    break
    except Exception:
        deps.impact_unknown.append("presets")


def _ambience_store_dependencies(ref: str, deps: Dependencies) -> None:
    try:
        from fastprompter.core.ambience_store import AmbienceStore

        store = AmbienceStore()
        for rule in store.load_rules():
            if getattr(rule, "sound_ref", None) == ref:
                deps.ambience_rules.append(str(getattr(rule, "id", "") or ""))
    except Exception:
        deps.impact_unknown.append("ambience")


def dependencies_for_ref(
    ref: str,
    *,
    data: dict | None = None,
    problip_sound_ids: list[str] | None = None,
    include_persistent_stores: bool = True,
) -> Dependencies:
    """Enumerate every known consumer of one managed ``user:`` ref.

    ``data`` is the active profile state dict (``sound_events`` is read from
    it). ``problip_sound_ids`` is the live Problip pool. Persistent stores
    (presets, ambience) are read from disk unless ``include_persistent_stores``
    is False -- tests pass a private path through the modules' own defaults.
    """
    deps = Dependencies(ref=ref)
    if ref in (problip_sound_ids or []):
        deps.problip_pool = True
    if isinstance(data, dict):
        for event, config in (data.get("sound_events") or {}).items():
            if isinstance(config, dict) and config.get("file") == ref:
                deps.events.append(str(event))
    if include_persistent_stores:
        _preset_store_dependencies(ref, deps)
        _ambience_store_dependencies(ref, deps)
    return deps


def is_managed_ref(ref: str) -> bool:
    return sound_library.is_managed_ref(ref)
