"""T-1446 / SRC-142: RED controls for the audit/19.md three-wave handoff.

Thirteen verified findings arrived as one external audit and each belongs to its
own ticket in the source contract (SRC-142:CORE-001..005, W2-001..004,
PERF-001..004).  Each gets its own control here, because a passing quartet of
tests for one wave is not evidence for the other two.

Every control reproduces the auditor's own deterministic reproduction against
this checkout.  The CORE and W2 repairs were already present in the working
tree when this ticket entered BUILD, so their controls pin the behaviour that
must not regress; the four PERF repairs were made in this pass and their
controls are red-before / green-after.

* CORE-001 sync publication must refuse an UNREADABLE destination
* CORE-002 an explicit sign-out must not resurrect a backup credential
* CORE-003 fractional Freebucks balances survive the hours conversion
* CORE-004 account visibility follows one shared availability policy
* CORE-005 the hide-zero label describes both hidden conditions
* W2-001 a crafted batch journal cannot move a file outside the library
* W2-002 independent stores cannot interleave two replace_all generations
* W2-003 a non-finite persisted timer value cannot abort the whole list
* W2-004 an unsupported schema_version is refused, never silently rewritten
* PERF-001 malformed Markdown no longer rescans a traversed suffix
* PERF-002 BBCode parsing does not lowercase the document per code block
* PERF-003 a nested sound-library change becomes visible without a restart
* PERF-004 link-token overlap queries stay sub-quadratic on dense blocks

Nothing here captures foreground focus, injects input, touches an audio device
or writes the operator's live data tree: every filesystem case builds its own
temporary root, and the timing cases assert a growth RATIO rather than a wall
clock where they can.
"""

import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import interval_preset_store as ips  # noqa: E402
from fastprompter.core import (
    link_tokens,  # noqa: E402
    markdown_refs,  # noqa: E402
    project_sync,  # noqa: E402
    rich_preview,  # noqa: E402
    sound_library,  # noqa: E402
    sound_manager,  # noqa: E402
)
from fastprompter.core import timers as timers_mod  # noqa: E402

# ---------------------------------------------------------------------------
# CORE-001 — sync publication refuses an UNREADABLE destination
# ---------------------------------------------------------------------------


def test_core001_unreadable_destination_is_refused(tmp_path, monkeypatch):
    """An unreadable destination must not satisfy the missing-file gate."""
    destination = tmp_path / "silo.md"
    destination.write_text("ORIGINAL USER BYTES", encoding="utf-8")

    real_open = open

    def denied(path, *args, **kwargs):
        if os.path.abspath(str(path)) == os.path.abspath(str(destination)):
            raise PermissionError(13, "denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", denied)
    written, conflict = project_sync.compare_and_publish_text(
        str(destination), "APP BYTES", project_sync.MISSING_ON_DISK)
    monkeypatch.undo()

    assert written is None
    assert project_sync.is_unreadable_identity(conflict)
    assert destination.read_text(encoding="utf-8") == "ORIGINAL USER BYTES"


def test_core001_missing_destination_still_creates(tmp_path):
    destination = tmp_path / "new.md"
    written, conflict = project_sync.compare_and_publish_text(
        str(destination), "fresh", project_sync.MISSING_ON_DISK)
    assert conflict is None
    assert written == "fresh"
    assert destination.read_text(encoding="utf-8") == "fresh"


def test_core001_changed_destination_preserves_original(tmp_path):
    destination = tmp_path / "silo.md"
    destination.write_text("disk bytes", encoding="utf-8")
    stale = project_sync.raw_identity(b"something else")
    written, conflict = project_sync.compare_and_publish_text(
        str(destination), "app bytes", stale)
    assert written is None
    assert conflict == project_sync.raw_identity(b"disk bytes")
    assert destination.read_text(encoding="utf-8") == "disk bytes"


# ---------------------------------------------------------------------------
# CORE-002 — explicit sign-out is authoritative over the backup
# ---------------------------------------------------------------------------


def _freebuff_state(tmp_path, sessions):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"authSessions": sessions}), encoding="utf-8")
    return str(path)


def test_core002_signed_out_primary_refuses_the_backup(tmp_path):
    from fastprompter.core.usage_limits.providers import _freebuff_http as fb

    state = _freebuff_state(tmp_path, {})
    (tmp_path / "state.json.bak").write_text(json.dumps({
        "authSessions": {
            "https://www.codebuff.com": {"token": "OLD", "user": {"id": "u1"}},
        }
    }), encoding="utf-8")

    assert fb.read_token(state) == ""
    assert fb.read_account_user(state) == {}


def test_core002_corrupt_primary_still_recovers_from_backup(tmp_path):
    from fastprompter.core.usage_limits.providers import _freebuff_http as fb

    state = tmp_path / "state.json"
    state.write_text("{ not json", encoding="utf-8")
    (tmp_path / "state.json.bak").write_text(json.dumps({
        "authSessions": {
            "https://www.codebuff.com": {"token": "GOOD", "user": {"id": "u1"}},
        }
    }), encoding="utf-8")

    assert fb.read_token(str(state)) == "GOOD"


def test_core002_explicit_signout_is_detected_only_for_intact_state(tmp_path):
    from fastprompter.core.usage_limits.providers import _freebuff_http as fb

    assert fb._explicit_sign_out(_freebuff_state(tmp_path, {})) is True
    assert fb._explicit_sign_out(_freebuff_state(
        tmp_path, {"https://www.codebuff.com": {"token": "t"}})) is False


# ---------------------------------------------------------------------------
# CORE-003 — fractional Freebucks balances survive conversion
# ---------------------------------------------------------------------------


def test_core003_fractional_wallet_keeps_its_value():
    from fastprompter.core.usage_limits.providers import freebuff as fbp

    assert fbp._to_hours(0) == 0.0
    assert fbp._to_hours(4) == pytest.approx(0.8)
    assert fbp._to_hours(7.5) == pytest.approx(1.5)
    assert fbp._to_hours(30) == pytest.approx(6.0)


def test_core003_non_numeric_and_non_finite_are_not_zero():
    from fastprompter.core.usage_limits.providers import freebuff as fbp

    assert fbp._to_hours(None) is None
    assert fbp._to_hours(float("inf")) is None
    assert fbp._to_hours(float("nan")) is None
    assert fbp._to_hours(-1) is None


# ---------------------------------------------------------------------------
# CORE-004 — one shared account-visibility policy
# ---------------------------------------------------------------------------


def test_core004_unknown_snapshot_stays_diagnostically_visible():
    """The available-only filter must not classify ERROR/UNKNOWN as available
    by an early append, yet the diagnostic surface stays reachable."""
    from fastprompter.core.usage_limits import model
    from fastprompter.core.usage_limits.service import ServiceState
    from fastprompter.ui.limit_account_selector import visible_quota_accounts

    account = model.AccountRef(
        provider_id="claude", stable_id="a", display_name="CL1",
        source_kind="configured")
    service = type("S", (), {})()
    service.state_copy = ServiceState(
        accounts=[account],
        snapshots={account.key: model.UsageSnapshot(
            account=account, status=model.ERROR, windows=[])},
    )
    shown = visible_quota_accounts({}, service, hide_unusable=True)
    assert [a.key for a in shown] == [account.key]


def test_core004_exhausted_ok_account_is_hidden_when_unusable():
    from fastprompter.core.usage_limits import model
    from fastprompter.core.usage_limits.service import ServiceState
    from fastprompter.ui.limit_account_selector import visible_quota_accounts

    account = model.AccountRef(
        provider_id="claude", stable_id="b", display_name="CL2",
        source_kind="configured")
    window = model.UsageWindow(
        key="five_hour", duration_minutes=300, available=True,
        used_percent=100.0, remaining_percent=0.0)
    service = type("S", (), {})()
    service.state_copy = ServiceState(
        accounts=[account],
        snapshots={account.key: model.UsageSnapshot(
            account=account, status=model.OK, windows=[window])},
    )
    shown = visible_quota_accounts({}, service, hide_unusable=True)
    assert shown == []


# ---------------------------------------------------------------------------
# CORE-005 — the hide-exhausted label states the single hidden condition
# ---------------------------------------------------------------------------


def test_core005_hide_zero_label_names_both_conditions():
    """Guard kept, contract corrected by T-1462.

    The old label said "0% used or 0% left", which falsely called an untouched
    100% quota unusable. The corrected UI says only genuine exhaustion (0%
    left) hides an account, and says so in BOTH checkbox copies.
    """
    source = open(os.path.join(
        os.path.dirname(__file__), "..", "src", "fastprompter", "ui",
        "limit_settings_dialog.py"), encoding="utf-8").read()
    assert source.count("Hide exhausted accounts (0% left)") == 2
    assert "0% used or 0% left" not in source


# ---------------------------------------------------------------------------
# W2-001 — a crafted batch journal cannot escape the library
# ---------------------------------------------------------------------------


def test_w2_001_journal_traversal_is_refused(tmp_path):
    store_dir = tmp_path / "presets"
    store_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("ORIGINAL_OUTSIDE_STORE", encoding="utf-8")

    staging = store_dir / ".batch-staging-demo"
    staging.mkdir()
    (staging / "forged.json").write_text(
        json.dumps({"schema_version": 1, "id": "x"}), encoding="utf-8")
    (store_dir / ".batch-journal.json").write_text(json.dumps({
        "token": "demo",
        "moves": [{"src": "forged.json", "dst": "../outside.json"}],
        "stale": [],
    }), encoding="utf-8")

    store = ips.IntervalPresetStore(str(store_dir))
    # A journal that names a destination outside the library is refused as a
    # transaction, not obeyed: recovery keeps it, reports the problem, and the
    # file outside the store is never touched. The refusal is the documented
    # "safe fallback OR isolated refusal" branch -- load() itself stays total.
    assert store.load() == []
    assert store.recovery_problem is not None
    assert outside.read_text(encoding="utf-8") == "ORIGINAL_OUTSIDE_STORE"


def test_w2_001_validate_accepts_a_real_journal_shape():
    journal = {
        "token": "deadbeef",
        "moves": [{"src": "deadbeef-p.json", "dst": "p.json"}],
        "stale": [],
    }
    assert ips.validate_batch_journal(journal) is journal


def test_w2_001_validate_accepts_a_foreign_producers_journal():
    """The safety rule is "single safe path segment", not "the alphabet this
    build happens to mint". A journal written by another producer (a non-hex
    token, a non-hex transfer id) is still a legitimate transaction to finish,
    and SRC-138/§06 depends on exactly that shape; pinning the alphabet refuses
    it and strands its staged generation -- the defect the repair exists to
    prevent. It must stay accepted while traversal stays refused.
    """
    journal = {
        "token": "5ta1e001",
        "moves": [{"src": "x-p0.json", "dst": "p0.json"}],
        "stale": [],
    }
    assert ips.validate_batch_journal(journal) is journal


@pytest.mark.parametrize("bad", [
    {"token": "..", "moves": [], "stale": []},
    {"token": "abc", "moves": [{"src": "a.json", "dst": "../x.json"}], "stale": []},
    {"token": "abc", "moves": [{"src": "/abs/x.json", "dst": "x.json"}], "stale": []},
    {"token": "abc", "moves": [{"src": "abc-x.json", "dst": "y.json"}], "stale": []},
    # A drive-relative name is an escape even without a separator: "C:a.json"
    # resolves against the drive's own CWD, not the store directory.
    {"token": "abc", "moves": [{"src": "C:a.json", "dst": "a.json"}], "stale": []},
    {"token": "abc", "moves": [{"src": "a.json", "dst": "C:a.json"}], "stale": []},
])
def test_w2_001_invalid_journals_are_refused(bad):
    with pytest.raises(ips.PresetValidationError):
        ips.validate_batch_journal(bad)


# ---------------------------------------------------------------------------
# W2-002 — two stores cannot interleave replace_all generations
# ---------------------------------------------------------------------------


def _preset(**overrides):
    doc = {
        "schema_version": 1,
        "id": overrides.get("id", "p"),
        "name": overrides.get("name", "P"),
        "kind": ips.KIND_SINGLE,
        "rules": [{
            "name": "R", "minutes": 30, "enabled": True, "sound": "",
            "volume": 0.05, "show_notification": True, "show_in_top_bar": False,
            "align_mode": "clock", "all_day": False,
            "start_minute": 540, "end_minute": 600,
        }],
    }
    doc.update(overrides)
    return doc


def test_w2_002_concurrent_replace_all_never_mixes_generations(tmp_path):
    store_dir = tmp_path / "presets"
    store_dir.mkdir()
    a = ips.IntervalPresetStore(str(store_dir))
    b = ips.IntervalPresetStore(str(store_dir))
    a.create_preset("seed", _preset(id="seed")["rules"])

    results = {}

    def run(store, tag):
        try:
            store.replace_all([
                _preset(id=f"{tag}1", name=f"{tag}1"),
                _preset(id=f"{tag}2", name=f"{tag}2"),
            ])
            results[tag] = "ok"
        except Exception as exc:                       # noqa: BLE001
            results[tag] = type(exc).__name__

    threads = [threading.Thread(target=run, args=(a, "A")),
               threading.Thread(target=run, args=(b, "B"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ids = sorted(doc["id"] for doc in ips.IntervalPresetStore(
        str(store_dir)).load())
    # The final library is ONE coherent generation, never {A1,A2,B1,B2}.
    assert ids in (["A1", "A2"], ["B1", "B2"])


def test_w2_002_a_lone_replace_all_is_coherent(tmp_path):
    store_dir = tmp_path / "presets"
    store_dir.mkdir()
    store = ips.IntervalPresetStore(str(store_dir))
    store.create_preset("seed", _preset(id="seed")["rules"])
    store.replace_all([_preset(id="solo1", name="solo1")])
    ids = sorted(doc["id"] for doc in
                 ips.IntervalPresetStore(str(store_dir)).load())
    assert ids == ["solo1"]


# ---------------------------------------------------------------------------
# W2-003 — a malformed timer value cannot abort the list
# ---------------------------------------------------------------------------


def _timer_doc(**overrides):
    doc = {
        "name": "T", "description": "", "target": "2030-01-01T10:00:00",
        "repeat": "none", "sound": "tick", "volume": 5, "enabled": True,
        "id": "t1", "interval_minutes": 30, "kind": "alarm",
        "sound_rules": [],
    }
    doc.update(overrides)
    return doc


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_w2_003_non_finite_interval_is_isolated(value):
    # W2-003: a non-finite persisted number used to raise OverflowError out of
    # int(), which no except clause covered, so ONE bad timer aborted the whole
    # startup load. The contract is "safe fallback OR isolated refusal": the
    # healer now floors it to the documented default and the list still loads
    # both timers, the malformed value never escaping as a live field.
    timers = timers_mod.load_timers([
        _timer_doc(id="bad", interval_minutes=value),
        _timer_doc(id="good"),
    ])
    assert [t.id for t in timers] == ["bad", "good"]
    healed = next(t for t in timers if t.id == "bad")
    assert healed.interval_minutes == timers_mod.DEFAULT_INTERVAL_MINUTES


def test_w2_003_non_finite_sound_rule_bound_is_isolated():
    timers = timers_mod.load_timers([
        _timer_doc(id="bad", sound_rules=[{
            "name": "R", "minutes": 30, "enabled": True, "sound": "tick",
            "volume": 0.05, "show_notification": True, "show_in_top_bar": False,
            "align_mode": "clock", "all_day": False,
            "start_minute": float("inf"), "end_minute": 600,
        }]),
        _timer_doc(id="good"),
    ])
    assert [t.id for t in timers] == ["bad", "good"]
    rule = next(t for t in timers if t.id == "bad").sound_rules[0]
    assert rule["start_minute"] == 0            # healed, never inf
    assert rule["end_minute"] == 600


# ---------------------------------------------------------------------------
# W2-004 — an unsupported schema_version is refused, never rewritten
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", [0, -1, 1.5, 99])
def test_w2_004_unsupported_schema_version_is_refused(tmp_path, version):
    store_dir = tmp_path / "presets"
    store_dir.mkdir()
    document = _preset(id="p", name="P")
    document["schema_version"] = version
    (store_dir / "p.json").write_text(json.dumps(document), encoding="utf-8")
    original = (store_dir / "p.json").read_bytes()

    # W2-004: the cold-load path used its own lossy int(version) and accepted
    # 0, negatives and fractions, which the next unrelated edit then rewrote to
    # 1 -- losing the document's declared identity. Load now applies the SAME
    # rule as import: a version this build cannot read is SKIPPED, its bytes
    # left on disk untouched, never reinterpreted or rewritten.
    assert ips.IntervalPresetStore(str(store_dir)).load() == []
    assert (store_dir / "p.json").read_bytes() == original
    with pytest.raises(ips.PresetValidationError):
        ips.clean_preset(document, strict=True)


def test_w2_004_version_1_round_trips(tmp_path):
    store_dir = tmp_path / "presets"
    store_dir.mkdir()
    store = ips.IntervalPresetStore(str(store_dir))
    created = store.create_preset("P", _preset(id="p")["rules"])
    assert created["schema_version"] == ips.SCHEMA_VERSION
    assert interval_preset_store_roundtrip(store)


def interval_preset_store_roundtrip(store):
    return any(doc["name"] == "P" for doc in store.load(force=True))


# ---------------------------------------------------------------------------
# PERF-001 — malformed Markdown no longer rescans a traversed suffix
# ---------------------------------------------------------------------------


def _growth_ratio(call, size):
    def timed(n):
        text = "[x](" * n
        start = time.perf_counter()
        call(text)
        return time.perf_counter() - start

    small = max(timed(size), 1e-6)
    large = timed(size * 4)
    return large / small


def test_perf001_unclosed_links_do_not_scale_quadratically():
    # 4x the input must not cost ~16x the time. A linear parser stays well
    # under the quadratic signature; the bound is deliberately loose so a
    # slow or loaded machine cannot make this flaky.
    assert _growth_ratio(markdown_refs.find_markdown_refs, 250) < 8.0


def test_perf001_later_valid_reference_still_recovers():
    refs = markdown_refs.find_markdown_refs("[a](broken [b](ok)")
    assert [r.raw_target for r in refs] == ["ok"]


def test_perf001_nested_and_escaped_destinations_are_unchanged():
    assert markdown_refs.find_markdown_refs("[a](p(1).png)")[0].raw_target == "p(1).png"
    assert markdown_refs.find_markdown_refs("[a](<a b.png>)")[0].raw_target == "<a b.png>"
    assert markdown_refs.find_markdown_refs("[a](dest \"title\")")[0].raw_target == "dest"


# ---------------------------------------------------------------------------
# PERF-002 — BBCode parsing does not lowercase the document per code block
# ---------------------------------------------------------------------------


def test_perf002_many_code_blocks_do_not_scale_quadratically():
    def timed(n):
        text = "".join(f"[code]x{i}[/code]" for i in range(n))
        start = time.perf_counter()
        rich_preview.parse_bbcode(text)
        return time.perf_counter() - start

    timed(200)                       # warm up import/JIT-ish first-call noise
    small = max(min(timed(250) for _ in range(3)), 1e-5)
    large = min(timed(1000) for _ in range(3))
    # 4x the input must not cost ~16x the time. The bound is loose so a loaded
    # machine cannot make a linear parser look quadratic.
    assert large / small < 12.0


def test_perf002_lowering_happens_at_most_once_per_parse(monkeypatch):
    calls = {"n": 0}
    real_lower = str.lower

    class Counting(str):
        def lower(self):
            calls["n"] += 1
            return real_lower(self)

    source = Counting("".join(f"[code]A{i}[/code]" for i in range(50)))
    rich_preview.parse_bbcode(source)

    # The old shape called source.lower() once per [code] block; the repair
    # computes it at most once and only when a [code] block is actually seen.
    assert calls["n"] <= 1


def test_perf002_code_content_stays_literal_and_case_exact():
    rendered = rich_preview.render("[code]MiXeD CaSe[/code]")
    assert "MiXeD CaSe" in rendered.plain_body
    lowered = rich_preview.render("[CODE]x[/CoDe]")
    assert "x" in lowered.plain_body


# ---------------------------------------------------------------------------
# PERF-003 — a nested sound-library change becomes visible
# ---------------------------------------------------------------------------


def test_perf003_nested_addition_converges_within_the_bound(tmp_path, monkeypatch):
    root = tmp_path / "sounds"
    nested = root / "cs_style"
    nested.mkdir(parents=True)
    (nested / "first.wav").write_text("x", encoding="utf-8")

    sound_manager._DISCOVERED_CACHE.clear()
    monkeypatch.setattr(sound_manager, "_DISCOVERY_REFRESH_SECONDS", 0.0)
    assert sound_manager.discover_sound_files(str(root)) == ["cs_style/first.wav"]

    (nested / "second.wav").write_text("y", encoding="utf-8")
    assert "cs_style/second.wav" in sound_manager.discover_sound_files(str(root))


def test_perf003_app_owned_import_bumps_the_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(sound_library, "managed_root", lambda: str(tmp_path))
    source = tmp_path / "src.wav"
    source.write_bytes(b"RIFF....WAVEfmt ")
    before = sound_library.library_generation()
    ref = sound_library.import_file(str(source), subdir="imported")
    assert ref
    assert sound_library.library_generation() == before + 1


def test_perf003_unchanged_library_uses_the_cache(tmp_path, monkeypatch):
    root = tmp_path / "sounds"
    root.mkdir()
    (root / "a.wav").write_text("x", encoding="utf-8")
    sound_manager._DISCOVERED_CACHE.clear()
    assert sound_manager.discover_sound_files(str(root)) == ["a.wav"]

    def boom(*args, **kwargs):
        raise AssertionError("re-walked an unchanged library")

    monkeypatch.setattr(sound_manager.os, "walk", boom)
    assert sound_manager.discover_sound_files(str(root)) == ["a.wav"]


# ---------------------------------------------------------------------------
# PERF-004 — link-token overlap queries stay sub-quadratic
# ---------------------------------------------------------------------------


def test_perf004_dense_block_does_not_scale_quadratically():
    def timed(n):
        text = ("`c` https://e.com/x ") * n
        start = time.perf_counter()
        link_tokens.tokenize_block(text)
        return time.perf_counter() - start

    small = max(timed(250), 1e-6)
    large = timed(1000)
    assert large / small < 12.0


def test_perf004_interval_query_matches_the_linear_oracle():
    def linear(spans, start, end):
        return any(start < b and a < end for a, b in spans)

    spans = [(1, 5), (10, 20), (30, 31)]
    for start in range(0, 35):
        for end in range(start, 35):
            assert link_tokens._overlaps(spans, start, end) == linear(
                spans, start, end)


def test_perf004_claimed_spans_stay_ordered_and_disjoint():
    spans: list[tuple[int, int]] = []
    for start, end in [(5, 10), (1, 3), (8, 20), (40, 45), (20, 22)]:
        link_tokens._claim(spans, start, end)
    for index in range(1, len(spans)):
        assert spans[index - 1][1] < spans[index][0]
