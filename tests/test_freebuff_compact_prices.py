"""T-1243 spec 25-27: the Freebuff model-price table is compact and bounded.

The first implementation joined every model into one line, which grew the
hover panel into a horizontal banner.  Prices repeat heavily, so the useful
shape is one row per PRICE, a bounded subset in the hover panel, and the
full table in Settings.
"""

import pytest

from fastprompter.core.usage_limits.freebuff_format import (
    HOVER_MODEL_BUDGET,
    compact_price_lines,
    format_price,
    full_price_rows,
    price_buckets,
    short_model_id,
)

PRICES = {
    "upstage/solar-pro4.0": 0,
    "zhipu/glm-5.3-flash": 0,
    "moonshot/kimi-k3-eco": 5,
    "xiaomi/mimo-v2.5": 10,
    "deepseek/deepseek-v4-flash": 15,
    "muse/muse-spark": 15,
    "openai/gpt-5.6-luna": 20,
    "google/gemini-3-pro": 20,
    "google/gemini-3-ultra": 50,
}


class TestShortIds:
    def test_the_namespace_prefix_is_dropped(self):
        assert short_model_id("openai/gpt-5.6-luna") == "gpt-5.6-luna"

    def test_a_deep_path_keeps_only_the_final_component(self):
        assert short_model_id("a/b/c/name") == "name"

    def test_a_bare_name_survives(self):
        assert short_model_id("name") == "name"

    def test_junk_becomes_empty(self):
        assert short_model_id(None) == ""
        assert short_model_id("   ") == ""


class TestBuckets:
    def test_models_are_grouped_by_price(self):
        buckets = price_buckets(PRICES)
        prices = [price for price, _names in buckets]
        assert prices == [0, 5, 10, 15, 20, 50]

    def test_prices_ascend(self):
        prices = [p for p, _ in price_buckets(PRICES)]
        assert prices == sorted(prices)

    def test_names_inside_a_bucket_are_sorted(self):
        buckets = dict(price_buckets(PRICES))
        assert buckets[15] == sorted(buckets[15], key=str.lower)

    def test_names_are_short_ids(self):
        buckets = dict(price_buckets(PRICES))
        assert "gpt-5.6-luna" in buckets[20]
        assert not any("/" in name for _p, names in price_buckets(PRICES)
                       for name in names)

    def test_non_numeric_prices_are_dropped_not_guessed(self):
        buckets = price_buckets({"a/x": "free", "a/y": None, "a/z": 5,
                                 "a/w": True})
        assert buckets == [(5.0, ["z"])]

    def test_a_non_dict_is_empty(self):
        assert price_buckets(None) == []
        assert price_buckets([]) == []


class TestFormatPrice:
    def test_integers_stay_integers(self):
        assert format_price(0) == "0"
        assert format_price(20.0) == "20"

    def test_fractions_survive(self):
        assert format_price(12.5) == "12.5"


class TestCompactLines:
    def test_one_line_per_price_bucket(self):
        lines, _omitted = compact_price_lines(PRICES, budget=100)
        assert len(lines) == 6
        assert lines[0][0] == "0"

    def test_names_in_a_line_are_comma_joined(self):
        lines, _ = compact_price_lines(PRICES, budget=100)
        zero = dict(lines)["0"]
        assert ", " in zero

    def test_the_model_budget_is_respected(self):
        lines, omitted = compact_price_lines(PRICES, budget=4)
        shown = sum(len(names.split(", ")) for _p, names in lines)
        assert shown <= 4
        assert omitted == len(PRICES) - shown

    def test_nothing_is_lost_silently(self):
        lines, omitted = compact_price_lines(PRICES, budget=4)
        shown = sum(len(names.split(", ")) for _p, names in lines)
        assert shown + omitted == len(PRICES)

    def test_the_cheapest_models_are_the_ones_that_fit(self):
        lines, _ = compact_price_lines(PRICES, budget=3)
        assert lines[0][0] == "0"

    def test_the_default_budget_is_the_documented_one(self):
        assert 10 <= HOVER_MODEL_BUDGET <= 12
        lines, omitted = compact_price_lines(PRICES)
        shown = sum(len(names.split(", ")) for _p, names in lines)
        assert shown == len(PRICES)      # this fixture fits
        assert omitted == 0

    def test_a_big_catalog_is_bounded(self):
        big = {f"vendor/model-{i:03d}": (i % 7) * 5 for i in range(300)}
        lines, omitted = compact_price_lines(big)
        shown = sum(len(names.split(", ")) for _p, names in lines)
        assert shown <= HOVER_MODEL_BUDGET
        assert omitted == 300 - shown

    def test_an_empty_catalog_renders_nothing(self):
        assert compact_price_lines({}) == ([], 0)


class TestFullTable:
    def test_every_model_appears(self):
        rows = full_price_rows(PRICES)
        assert len(rows) == len(PRICES)

    def test_it_is_sorted_by_price_then_name(self):
        rows = full_price_rows(PRICES)
        keys = [(float(price), name.lower()) for name, price in rows]
        assert keys == sorted(keys)

    def test_the_two_views_agree_on_ordering(self):
        rows = [name for name, _p in full_price_rows(PRICES)]
        flat = [name for _p, names in price_buckets(PRICES) for name in names]
        assert rows == flat

    def test_prices_are_labels_not_floats(self):
        for _name, price in full_price_rows(PRICES):
            assert isinstance(price, str)


class TestHoverRendering:
    def test_the_gauge_summarises_prices_instead_of_listing_them(self, qapp):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QApplication

        from fastprompter.core.usage_limits.model import UsageSnapshot, UsageWindow
        from fastprompter.ui.limit_gauges import LimitGauges
        from tests.test_usage_limits_gauge_layout import (
            _account,
            _Service,
            _State,
            _Win,
        )

        account = _account("freebuff", "fb")
        snapshot = UsageSnapshot(
            account=account, status="OK", fetched_at=1_800_000_000.0,
            plan_type="starter",
            windows=[UsageWindow("daily_amount", 1440, True, 100.0, 0.0,
                                 1_800_003_600.0, used_amount=100.0,
                                 remaining_amount=0.0, limit_amount=100.0,
                                 unit="FB")],
            provider_metadata={"wallet_balance": 30.0,
                               "wallet_monthly_bonus": 300.0,
                               "model_prices": dict(PRICES)})
        win = _Win()
        win.data["limit_accounts"] = [account.key]
        service = _Service(_State([account], {account.key: snapshot}))
        gauge = LimitGauges(win, service)
        try:
            QApplication.sendEvent(gauge, QEvent(QEvent.Type.Enter))
            html = gauge._hover_card._label.text()
            # The catalogue does NOT belong in a hover panel: one summary
            # line, and the full table lives in AI Limit Settings.
            assert "9 model prices" in html
            assert "0-50 FB/h" in html
            assert "AI Limit Settings" in html
            assert "gpt-5.6-luna" not in html
            assert "openai/" not in html
        finally:
            gauge.hide_hover_card(immediate=True)
            win.deleteLater()


@pytest.mark.parametrize("budget", [1, 2, 5, 12, 40])
def test_the_budget_is_never_exceeded(budget):
    lines, omitted = compact_price_lines(PRICES, budget=budget)
    shown = sum(len(names.split(", ")) for _p, names in lines)
    assert shown <= budget
    assert shown + omitted == len(PRICES)
