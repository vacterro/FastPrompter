"""T-812 regression: every key in ``FastPrompter._resync_profile_widgets``'s
``_CHECKS`` registry must be a CANONICAL, actually-used persisted key — never a
stale/dead alias. A wrong key there makes profile switches stamp checkbox
state from the wrong ``self.data`` slot, contradicting the active profile.

This is a source-level invariant so it runs without the full window: it parses
``main.py``, extracts the registry, and proves each key is one that the rest of
the code actually reads/writes via ``self.data``.
"""

import os
import re

_MAIN = os.path.join(os.path.dirname(__file__), "..", "src",
                     "fastprompter", "main.py")


def _read():
    with open(_MAIN, encoding="utf-8") as f:
        return f.read()


def _registry(src):
    m = re.search(r"_CHECKS = \((.*?)\n        \)", src, re.S)
    if not m:
        raise AssertionError("could not locate _CHECKS in main.py")
    body = m.group(1)
    return re.findall(
        r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', body)


def _used_keys(src):
    keys = set()
    keys |= set(re.findall(r'self\.data\.get\(\s*["\']([A-Za-z_]+)["\']', src))
    keys |= set(re.findall(r'self\.data\[["\']([A-Za-z_]+)["\']', src))
    keys |= set(re.findall(r'self\.data\.update\(\s*\{\s*["\']?([A-Za-z_]+)',
                            src))
    return keys


def test_resync_registry_keys_are_canonical_used_keys():
    src = _read()
    entries = _registry(src)
    assert entries, "registry parsed"
    used = _used_keys(src)
    for attr, key, default in entries:
        assert key in used, (
            f"resync key {key!r} for {attr} is not a canonical key used "
            f"anywhere in main.py — it is a stale/dead alias")


def test_resync_nine_specific_keys_are_canonical():
    src = _read()
    entries = {attr: key for attr, key, _d in _registry(src)}
    # map widget -> the canonical key its construction handler uses
    expected = {
        "cb_token_count": "show_token_count",
        "cb_zebra": "zebra_lines",
        "cb_double_line": "bullet_double_line",
        "cb_bold_titles": "bold_hash_titles",
        "cb_conceal": "live_preview_conceal",
        "cb_date_rect": "show_date_rect",
        "cb_timer_minutes": "timer_show_minutes",
        "cb_sound": "sound_ui",
        "cb_typewriter": "sound_typewriter",
    }
    for attr, key in expected.items():
        assert entries.get(attr) == key, (
            f"{attr} must resync from canonical key {key!r}, found "
            f"{entries.get(attr)!r}")


def test_resync_has_no_stale_sound_or_legacy_keys():
    src = _read()
    registry_keys = {key for _a, key, _d in _registry(src)}
    stale = {"token_count", "zebra", "double_line", "bold_titles", "conceal",
             "date_rect", "timer_minutes", "sound_enabled", "typewriter"}
    assert not (registry_keys & stale), (
        f"registry still carries stale keys: {registry_keys & stale}")


def test_sound_enabled_alias_removed_from_defaults():
    import fastprompter.core.default_profile as dp
    assert "sound_enabled" not in dp.DEFAULT_PROFILE, \
        "obsolete sound_enabled alias must be removed from the default profile"
    assert "sound_ui" in dp.DEFAULT_PROFILE
