"""T-1279 — the reset-queue hover is a STRUCTURED COLUMN table.

The tooltip used to be free-form lines ``N. Account · Pool · Window  Time``:
readable for three rows, useless for twelve, because the columns are not
columns and the one field the user actually reads ("time until this refills")
was the only one never aligned.

This suite pins the renderer and the wiring that replaced it:

* columns ``# | Account | Pool | Window | Left | Resets`` with a header row;
* a real rich-text table, never repeated-space alignment;
* ``Left`` right-aligned and always present;
* a long Pool truncates BEFORE ``Left`` can be pushed out;
* the queue ORDER is exactly ``reset_candidates`` order;
* a named-model reserve (Luna) appears as its own Pool row;
* the card is the EXISTING ``LimitHoverCard`` — no second hover system;
* geometry is stable across a one-second refresh.

T-1457-A added the sixth column (``Resets``): the ABSOLUTE reset instant beside
the relative countdown. The tests below pin BOTH time facts, their agreement on
one epoch, and the em-dash fallback for a row with no usable instant.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    qualified_key,
    reset_candidates,
)
from fastprompter.core.usage_limits.model import AccountRef as AR
from fastprompter.ui.reset_queue_card import (
    ACCOUNT_CHARS,
    COLUMNS,
    MISSING_MOMENT,
    POOL_CHARS,
    elide,
    moment_label,
    render_table,
    reset_rows,
    window_label,
)

LUNA_POOL = "base_model_inference"


def _account(provider, sid, name):
    return AR(provider_id=provider, stable_id=sid, display_name=name,
              source_kind="test")


def _snapshot(account, windows):
    return UsageSnapshot(account=account, status=OK, windows=list(windows),
                         fetched_at=time.time())


def _candidates():
    """Three providers, four candidates, one named reserve — realistic queue."""
    now = time.time()
    codex = _snapshot(_account("codex", "c1", "Codex 1"), [
        UsageWindow(FIVE_HOUR, 300, True, 10, 90, now + 600),
        UsageWindow(WEEKLY, 10080, True, 10, 90, now + 86400),
    ])
    claude = _snapshot(_account("claude", "cl1", "Claude"), [
        UsageWindow(FIVE_HOUR, 300, True, 10, 90, now + 120),
    ])
    multi = _snapshot(_account("codex", "c2", "Codex 2"), [
        UsageWindow(qualified_key(WEEKLY, "codex"), 10080, True, 0, 0,
                    now + 172800, group="codex", group_label="Codex"),
        UsageWindow(qualified_key(WEEKLY, LUNA_POOL), 10080, True, 100, 100,
                    now + 259200, group=LUNA_POOL,
                    group_label="GPT Reserve", model_slug="gpt-5.6-luna"),
    ])
    snaps = {s.account.key: s for s in (codex, claude, multi)}
    return reset_candidates(snaps)


def _render(cands=None, now=None):
    cands = cands if cands is not None else _candidates()
    now = time.time() if now is None else now
    rows = reset_rows(cands, now, name_for=lambda a: a.display_name)
    return rows, render_table(rows)


class TestColumns:
    def test_header_row_names_every_column(self):
        _rows, html = _render()
        for column in COLUMNS:
            assert f">{column}</td>" in html

    def test_the_six_column_contract_is_explicit(self):
        """T-1457-A: six columns, and the sixth is the ABSOLUTE reset instant."""
        assert COLUMNS == ("#", "Account", "Pool", "Window", "Left", "Resets")
        assert len(COLUMNS) == 6

    def test_every_candidate_gets_one_structured_row(self):
        cands = _candidates()
        rows, html = _render(cands)
        assert len(rows) == len(cands)
        assert html.count("<tr>") == len(cands) + 1     # + header
        for index, row in enumerate(rows, start=1):
            assert row["n"] == index

    def test_it_is_a_real_table_not_space_padding(self):
        _rows, html = _render()
        assert "<table" in html
        assert "&nbsp;&nbsp;&nbsp;" not in html
        assert html.count("<td") >= len(COLUMNS) * 2

    def test_left_is_right_aligned_and_always_present(self):
        _rows, html = _render()
        assert "text-align:right" in html
        for row in _rows:
            assert row["left"]                       # never empty
            assert row["left"] in html

    def test_short_windows_render_compactly(self):
        assert window_label(UsageWindow(FIVE_HOUR, 300, True, 0, 100, None)) == "5h"
        assert window_label(UsageWindow(WEEKLY, 10080, True, 0, 100, None)) == "Weekly"
        assert window_label(UsageWindow("window_1440m", 1440, True, 0, 100,
                                        None)) == "1d"


class TestResetInstantColumn:
    """T-1457-A: the sixth column, and the fallback that keeps it honest."""

    def test_both_time_facts_come_from_the_same_epoch(self):
        cands = _candidates()
        now = time.time()
        rows = reset_rows(cands, now, name_for=lambda a: a.display_name)
        for row, cand in zip(rows, cands):
            assert row["resets"] == moment_label(cand.resets_at_epoch, now)

    def test_same_day_resets_show_a_clock_time_and_later_ones_a_weekday(self):
        now = time.time()
        assert moment_label(now + 120, now) == time.strftime(
            "%H:%M", time.localtime(now + 120))
        later = moment_label(now + 3 * 86400, now)
        assert later == time.strftime("%a %H:%M", time.localtime(now + 3 * 86400))
        assert later != moment_label(now + 120, now)

    def test_a_missing_instant_is_an_em_dash_not_a_bogus_date(self):
        for bad in (None, "", 0, -1, "soon", object(), float("nan")):
            assert moment_label(bad, time.time()) == MISSING_MOMENT

    def test_the_column_survives_a_row_without_an_instant(self):
        """A row dict lacking ``resets`` still renders all six columns."""
        rows = [{"n": 1, "account": "A", "pool": "", "window": "5h",
                 "left": "1m 00s", "color": ""}]
        html = render_table(rows)
        assert html.count("<td") == len(COLUMNS) * 2   # header + one row
        assert MISSING_MOMENT in html

    def test_the_instant_column_is_labelled_by_the_caller(self):
        cands = _candidates()
        now = time.time()
        rows = reset_rows(cands, now, name_for=lambda a: a.display_name)
        html = render_table(rows, labels={"Resets": "Сбросы"})
        assert ">Сбросы</td>" in html
        for row in rows:
            assert row["resets"] in html


class TestTruncation:
    def test_long_pool_is_truncated_before_left(self):
        now = time.time()
        acct = _account("codex", "x", "A" * 90)
        snap = _snapshot(acct, [
            UsageWindow(qualified_key(WEEKLY, "p"), 10080, True, 0, 100,
                        now + 600, group="p", group_label="P" * 90),
        ])
        cands = reset_candidates({snap.account.key: snap})
        rows, html = _render(cands, now)
        # The RAW values are truncated by render_table, not by reset_rows.
        assert elide("P" * 90, POOL_CHARS) in html
        assert elide("A" * 90, ACCOUNT_CHARS) in html
        assert "P" * 90 not in html
        assert rows[0]["left"] in html               # Left survived truncation
        assert rows[0]["resets"] in html             # so did the instant

    def test_elide_never_exceeds_the_budget(self):
        assert len(elide("abcdef", 4)) == 4
        assert elide("abc", 4) == "abc"
        assert elide("", 4) == ""
        assert elide("abcd", 0) == ""


class TestOrderingAndPools:
    def test_order_is_exactly_reset_candidates_order(self):
        cands = _candidates()
        rows = reset_rows(cands, time.time(), name_for=lambda a: a.display_name)
        assert [r["account"] for r in rows] == [c.account.display_name
                                                for c in cands]
        epochs = [c.resets_at_epoch for c in cands]
        assert epochs == sorted(epochs)

    def test_luna_reserve_appears_as_its_own_pool_row(self):
        rows, html = _render()
        pools = [r["pool"] for r in rows]
        assert "GPT Reserve" in pools
        assert pools.count("GPT Reserve") == 1
        assert "GPT Reserve" in html

    def test_claude_current_session_keeps_its_vendor_name(self):
        rows, html = _render()
        claude = next(row for row in rows if row["account"] == "Claude")
        assert claude["window"] == "Session"
        assert ">Session</td>" in html

    def test_empty_queue_renders_the_header_only(self):
        assert "<table" not in render_table([], header="Next resets")


class TestColumnLabels:
    def test_labels_are_caller_translated_and_renderer_stays_pure(self):
        """The renderer never reads UI language state: the caller passes the
        translated labels (i18n follow-up to T-1279)."""
        cands = _candidates()
        rows = reset_rows(cands, time.time(),
                          name_for=lambda a: a.display_name)
        html = render_table(
            rows, header="Ближайшие сбросы",
            labels={"Account": "Аккаунт", "Pool": "Пул",
                    "Window": "Окно", "Left": "Осталось"})
        for translated in ("Аккаунт", "Пул", "Окно", "Осталось",
                           "Ближайшие сбросы"):
            assert translated in html
        for english in ("Account", "Pool", "Window", "Left"):
            assert f">{english}</td>" not in html
        assert ">#</td>" in html, "the # column is language-independent"
        assert "<table" in html

    def test_canonical_labels_exist_for_every_translatable_column(self):
        """Every labelled column has a canonical key, so no visible header
        can silently fall back to raw English in every locale."""
        from fastprompter.core.i18n.en import TRANSLATIONS as EN
        for column in COLUMNS:
            if column == "#":
                continue
            assert column in EN, (
                f"{column!r} has no canonical translation key")


class TestCardWiring:
    def test_the_label_opens_the_existing_hover_card(self, monkeypatch):
        """No second hover system: the owner must reuse LimitHoverCard."""
        import fastprompter.main as main_mod
        import fastprompter.ui.limit_hover_card as card_mod

        created = []

        class _FakeCard:
            def __init__(self, anchor):
                created.append(anchor)

            def isVisible(self):
                return True

            def show_card(self, html):
                created.append(html)

            def set_html(self, html):
                created.append(html)

            def schedule_hide(self):
                created.append("hide")

        monkeypatch.setattr(card_mod, "LimitHoverCard", _FakeCard)

        class _Lbl:
            def isVisible(self):
                return True

        owner = main_mod.FastPrompter.__new__(main_mod.FastPrompter)
        owner.lbl_limit_timer = _Lbl()
        owner._reset_hover_card = None
        owner._reset_queue_html = "<b>x</b>"
        owner._show_reset_hover_card()
        assert created and created[0] is owner.lbl_limit_timer
        assert "<b>x</b>" in created

    def test_no_card_is_created_when_the_queue_is_empty(self, monkeypatch):
        import fastprompter.main as main_mod
        import fastprompter.ui.limit_hover_card as card_mod

        made = []
        monkeypatch.setattr(card_mod, "LimitHoverCard",
                            lambda anchor: made.append(anchor))

        class _Lbl:
            def isVisible(self):
                return True

        owner = main_mod.FastPrompter.__new__(main_mod.FastPrompter)
        owner.lbl_limit_timer = _Lbl()
        owner._reset_hover_card = None
        owner._reset_queue_html = ""
        owner._show_reset_hover_card()
        assert made == []


class TestGeometryStability:
    def test_column_header_set_is_identical_across_a_refresh(self):
        """A one-second countdown change must not move the columns."""
        now = time.time()
        cands = _candidates()
        rows_a = reset_rows(cands, now, name_for=lambda a: a.display_name)
        rows_b = reset_rows(cands, now - 60, name_for=lambda a: a.display_name)
        assert [r["account"] for r in rows_a] == [r["account"] for r in rows_b]
        assert [r["pool"] for r in rows_a] == [r["pool"] for r in rows_b]
        assert [r["window"] for r in rows_a] == [r["window"] for r in rows_b]
        html_a = render_table(rows_a)
        html_b = render_table(rows_b)
        # Column starts come from FIXED td styles, so the structural elements
        # are byte-identical between the two renders.
        assert (html_a.count("<td") == html_b.count("<td"))
        assert (html_a.count("white-space:nowrap") ==
                html_b.count("white-space:nowrap"))
        for column in COLUMNS:
            assert html_a.count(f">{column}</td>") == html_b.count(
                f">{column}</td>")

    def test_first_render_equals_a_later_render_of_the_same_queue(self):
        """T-1457-A: no first-open jump — the column set and structure a card
        gets on its FIRST paint must match every later refresh, so the popup
        cannot grow a column or re-measure its widths once it is already open.
        """
        now = time.time()
        cands = _candidates()
        rows = reset_rows(cands, now, name_for=lambda a: a.display_name)

        def measure(text):
            return len(text) * 7

        from fastprompter.ui.reset_queue_card import required_width
        wide = required_width(rows, {}, measure)
        first = render_table(rows, available_width=wide + 40, measure=measure)
        later = render_table(rows, available_width=wide + 40, measure=measure)
        assert first == later
        assert first.count("<td") == len(COLUMNS) * (len(rows) + 1)

    def test_a_narrower_screen_stacks_account_and_pool_without_losing_a_column(
            self):
        """The compact composition keeps all six facts in four cells."""
        now = time.time()
        cands = _candidates()
        rows = reset_rows(cands, now, name_for=lambda a: a.display_name)

        def measure(text):
            return len(text) * 7

        from fastprompter.ui.reset_queue_card import (
            COMPACT_COLUMNS,
            required_width,
        )
        wide = required_width(rows, {}, measure)
        html = render_table(rows, available_width=wide - 1, measure=measure)
        assert "Account / Pool" in html
        assert html.count("<td") == len(COMPACT_COLUMNS) * (len(rows) + 1)
        for row in rows:
            assert row["left"] in html
            assert row["resets"] in html

