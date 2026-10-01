"""T-1378: Claude reset timestamps must normalize a naive ISO string as UTC.

The quota-reset contract says provider reset instants cross as numeric epochs
and that NAIVE provider output is DEFINED as UTC. Every provider parser in
this package honored that; `claude._parse_reset` was the lone outlier, calling
`datetime.timestamp()` on a naive value, which Python reads as LOCAL time --
so the same payload string put Claude's reset window hours away from Codex's.

The test pins the absolute epoch. That is the whole oracle: a local-time read
is off by exactly the host's UTC offset, so on any non-UTC machine the
pre-fix parser lands on a different number and the test goes red. It does not
need to change the process timezone, which `time.tzset()` cannot do on Windows.
"""

from __future__ import annotations

import time

from fastprompter.core.usage_limits.providers import claude as claude_mod
from fastprompter.core.usage_limits.providers import codex as codex_mod

# 2026-10-02T12:00:00 read as UTC.
EXPECTED_EPOCH = 1790942400.0

#: Non-zero on any machine that is not running UTC, which is what makes the
#: pre-fix parser fail here rather than only in another timezone.
HOST_UTC_OFFSET = time.timezone


def test_naive_reset_string_is_utc_by_definition():
    """The contract's own rule, asserted on the value the UI actually shows."""
    assert claude_mod._parse_reset("2026-10-02T12:00:00") == EXPECTED_EPOCH


def test_matches_the_codex_sibling():
    """Two providers, one payload string, one instant -- the ticket's own claim."""
    payload = "2026-10-02T12:00:00"
    assert claude_mod._parse_reset(payload) == codex_mod._epoch(payload)


def test_aware_input_is_untouched():
    """The fix must not re-attach an offset to a value that already carries one."""
    assert claude_mod._parse_reset("2026-10-02T12:00:00+00:00") == EXPECTED_EPOCH
    assert claude_mod._parse_reset("2026-10-02T14:00:00+02:00") == EXPECTED_EPOCH


def test_epoch_inputs_keep_their_existing_contract():
    """Numbers took the other branch and must keep passing through unchanged."""
    assert claude_mod._parse_reset(EXPECTED_EPOCH) == EXPECTED_EPOCH
    assert claude_mod._parse_reset(EXPECTED_EPOCH * 1000) == EXPECTED_EPOCH
    assert claude_mod._parse_reset(0) is None
    assert claude_mod._parse_reset(True) is None
    assert claude_mod._parse_reset("not a timestamp") is None


def test_campaign_expiry_uses_the_same_normalizer():
    """The second caller (_campaign_expiry) must not reintroduce the bug.

    Behavioral on purpose: a source-text assertion would pass even if the
    function grew its own naive `timestamp()` call. This was red before the fix
    for the same reason the first test was.
    """
    payload = "2026-10-02T12:00:00"
    assert claude_mod._campaign_expiry(payload) == EXPECTED_EPOCH
    assert claude_mod._campaign_expiry(payload) == claude_mod._parse_reset(payload)
