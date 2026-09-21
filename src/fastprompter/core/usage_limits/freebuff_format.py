"""Compact presentation of the Freebuff model-price table (T-1243 spec 25-27).

The vendor sends one price per model id, and there are dozens of them.  The
first implementation joined all of them into a single line::

    prices: solar-pro4.0 0 FB/h - glm-5.3-flash 0 FB/h - kimi-k3-eco 5 FB/h ...

which turned a small hover panel into a 1200px horizontal banner.  Prices
repeat heavily, so the useful shape is a bucket per price:

    Prices (FB/h)
      0:  solar-pro4.0, glm-5.3-flash
      5:  kimi-k3-eco
      10: mimo-v2.5

The hover panel shows a BOUNDED subset and says how many were left out; the
full table lives in the Freebuff settings detail.  Nothing is discarded --
the metadata stays in the snapshot either way.
"""

from __future__ import annotations

#: How many model names the hover panel may name before it defers to
#: Settings.  The panel is a summary, not a database dump.
HOVER_MODEL_BUDGET = 12


def short_model_id(model_id: str) -> str:
    """The final path/name component: ``vendor/family/name`` -> ``name``.

    Provider namespaces repeat on every row and carry no information the
    reader needs while comparing prices.
    """
    text = str(model_id or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def price_buckets(prices) -> list[tuple[float, list[str]]]:
    """``[(price, [short model names])]`` sorted by price, then by name."""
    if not isinstance(prices, dict):
        return []
    grouped: dict[float, list[str]] = {}
    for model_id, price in prices.items():
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        if price != price:                      # NaN
            continue
        name = short_model_id(model_id)
        if not name:
            continue
        grouped.setdefault(float(price), []).append(name)
    return [(price, sorted(names, key=str.lower))
            for price, names in sorted(grouped.items())]


def format_price(price: float) -> str:
    """``0`` / ``5`` / ``12.5`` -- integers stay integers."""
    if float(price).is_integer():
        return str(int(price))
    return f"{price:g}"


def compact_price_lines(prices, budget: int = HOVER_MODEL_BUDGET):
    """``(lines, omitted)`` for the hover panel.

    ``lines`` is ``[(price_label, "name, name")]`` covering at most ``budget``
    model names in ascending price order; ``omitted`` is how many names did
    not fit.  A bucket is never split across the boundary silently: the names
    that did not fit are simply counted.
    """
    lines: list[tuple[str, str]] = []
    shown = 0
    omitted = 0
    for price, names in price_buckets(prices):
        room = max(0, budget - shown)
        if room <= 0:
            omitted += len(names)
            continue
        take = names[:room]
        omitted += len(names) - len(take)
        shown += len(take)
        lines.append((format_price(price), ", ".join(take)))
    return lines, omitted


def full_price_rows(prices) -> list[tuple[str, str]]:
    """``[(model name, price label)]`` for the Settings detail table.

    Sorted by price ascending, then model name -- the same order as the
    hover buckets, so the two views never disagree.
    """
    rows: list[tuple[str, str]] = []
    for price, names in price_buckets(prices):
        label = format_price(price)
        rows.extend((name, label) for name in names)
    return rows
