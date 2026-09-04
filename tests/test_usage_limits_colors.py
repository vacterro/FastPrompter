"""Tests for the AI-limit colour palette and the reset-countdown rule.

Two behaviours that used to live in hardcoded constants are asserted here:

* every paintable role resolves through ONE place, so a user override reaches
  the gauge, the full-size bars, the countdown and the captions alike, while an
  untouched role keeps following the active theme;
* the countdown answers "what refills soonest" across every account and window,
  which is what made a Claude 5h window three hours out lose to a Codex weekly
  three days out.
"""

from __future__ import annotations

import time

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    provider_reset_color,
    qualified_key,
    soonest_reset,
)
from fastprompter.core.usage_limits.model import AccountRef as AR


class _Win:
    """The minimum a palette consumer needs: ``data`` and a theme cache."""

    def __init__(self, data=None, raw_colors=None):
        self.data = data if data is not None else {}
        self._theme_cache = {"raw_colors": raw_colors or {}}


class TestLimitColors:
    def test_an_untouched_role_follows_the_theme(self):
        from fastprompter.ui.limit_colors import resolve_hex
        win = _Win(raw_colors={"accent": "#112233"})
        assert resolve_hex(win, "good") == "#112233"

    def test_an_override_beats_the_theme(self):
        from fastprompter.ui.limit_colors import resolve_hex
        win = _Win(data={"limit_colors": {"good": "#ff0000"}},
                   raw_colors={"accent": "#112233"})
        assert resolve_hex(win, "good") == "#ff0000"

    def test_a_role_with_no_theme_counterpart_uses_its_default(self):
        from fastprompter.ui.limit_colors import ROLES_BY_KEY, resolve_hex
        win = _Win(raw_colors={"accent": "#112233"})
        assert resolve_hex(win, "bad") == ROLES_BY_KEY["bad"].default

    def test_a_garbage_override_is_ignored_not_painted(self):
        from fastprompter.ui.limit_colors import ROLES_BY_KEY, resolve_hex
        win = _Win(data={"limit_colors": {"bad": "not a colour",
                                          "nonsense_role": "#00ff00"}})
        assert resolve_hex(win, "bad") == ROLES_BY_KEY["bad"].default

    def test_a_string_profile_value_does_not_crash_the_palette(self):
        """An older/hand-edited profile can hold anything under that key."""
        from fastprompter.ui.limit_colors import limit_palette
        palette = limit_palette(_Win(data={"limit_colors": "nope"}))
        assert palette["good"].isValid()

    def test_every_role_resolves_to_a_valid_colour(self):
        from fastprompter.ui.limit_colors import ROLES, limit_palette
        palette = limit_palette(_Win())
        assert set(palette) == {role.key for role in ROLES}
        assert all(color.isValid() for color in palette.values())

    def test_the_gauge_and_the_bars_read_the_same_palette(self):
        """One override must recolour both surfaces, not one of them."""
        from fastprompter.ui import limit_gauges, limit_overview
        assert (limit_gauges.limit_palette
                is limit_overview.limit_palette)

    def test_vendor_countdown_colours_are_overridable(self):
        from fastprompter.ui.limit_colors import reset_color
        win = _Win(data={"limit_colors": {"reset_codex": "#010203"}})
        assert reset_color(win, "codex") == "#010203"
        # untouched vendors keep the model's Qt-free defaults
        assert reset_color(win, "claude") == provider_reset_color("claude")
        assert reset_color(win, "grok") is None

    def test_the_model_keeps_defaults_for_every_offered_vendor(self):
        """A vendor with a colour row must have a default behind it."""
        from fastprompter.ui.limit_colors import ROLES
        for role in ROLES:
            if role.key.startswith("reset_"):
                vendor = role.key.removeprefix("reset_")
                assert provider_reset_color(vendor) == role.default, vendor


def _snapshot(provider, windows, status=OK):
    account = AR(provider_id=provider, stable_id=provider,
                 display_name=provider, source_kind="test")
    return UsageSnapshot(account=account, status=status,
                         fetched_at=time.time(), windows=windows)


class TestSoonestReset:
    def test_a_nearer_five_hour_beats_a_distant_weekly(self):
        """The defect: Codex weekly 3 days out hid a Claude 5h 3 hours out."""
        now = time.time()
        claude = _snapshot("claude", [
            UsageWindow(FIVE_HOUR, 300, True, 64, 36, now + 3 * 3600),
            UsageWindow(WEEKLY, 10080, True, 54, 46, now + 5 * 86400)])
        codex = _snapshot("codex", [
            UsageWindow(WEEKLY, 10080, True, 100, 0, now + 3 * 86400)])
        provider, epoch = soonest_reset({
            claude.account.key: claude, codex.account.key: codex})
        assert provider == "claude"
        assert abs(epoch - (now + 3 * 3600)) < 1

    def test_a_gated_window_is_skipped(self):
        """Its longer sibling owns the wait; its own reset frees nothing."""
        now = time.time()
        codex = _snapshot("codex", [
            UsageWindow(FIVE_HOUR, 300, True, 0, 100, now + 3600),
            UsageWindow(WEEKLY, 10080, True, 100, 0, now + 4 * 86400)])
        provider, epoch = soonest_reset({codex.account.key: codex})
        assert provider == "codex"
        assert abs(epoch - (now + 4 * 86400)) < 1

    def test_a_window_in_another_pool_is_a_real_candidate(self):
        """Antigravity's Gemini 5h competes even while its Claude pool is dead."""
        now = time.time()
        snap = _snapshot("antigravity", [
            UsageWindow(qualified_key(FIVE_HOUR, "gemini"), 300, True,
                        90, 10, now + 1800, group="gemini"),
            UsageWindow(qualified_key(WEEKLY, "gemini"), 10080, True,
                        32, 68, now + 5 * 86400, group="gemini"),
            UsageWindow(qualified_key(WEEKLY, "third_party"), 10080, True,
                        100, 0, now + 29 * 3600, group="third_party"),
        ])
        provider, epoch = soonest_reset({snap.account.key: snap})
        assert provider == "antigravity"
        assert abs(epoch - (now + 1800)) < 1

    def test_a_hidden_account_never_wins(self):
        now = time.time()
        near = _snapshot("codex", [
            UsageWindow(FIVE_HOUR, 300, True, 50, 50, now + 60)])
        far = _snapshot("claude", [
            UsageWindow(WEEKLY, 10080, True, 50, 50, now + 86400)])
        provider, epoch = soonest_reset(
            {near.account.key: near, far.account.key: far},
            hidden_keys={near.account.key})
        assert provider == "claude"
        assert abs(epoch - (now + 86400)) < 1

    def test_windows_without_a_reset_time_are_not_candidates(self):
        """The Desktop sampler reports percentages but no reset instant."""
        now = time.time()
        sampler_only = _snapshot("claude", [
            UsageWindow(FIVE_HOUR, 300, True, 64, 36, None),
            UsageWindow(WEEKLY, 10080, True, 54, 46, None)])
        codex = _snapshot("codex", [
            UsageWindow(WEEKLY, 10080, True, 100, 0, now + 86400)])
        provider, epoch = soonest_reset({
            sampler_only.account.key: sampler_only, codex.account.key: codex})
        assert provider == "codex"
        assert abs(epoch - (now + 86400)) < 1

    def test_no_snapshots_means_no_countdown(self):
        assert soonest_reset({}) == (None, None)
