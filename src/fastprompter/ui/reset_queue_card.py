"""Structured column layout for the reset-queue hover (T-1279).

The soonest-reset label used to open a free-form ``setToolTip`` blob of lines
``N. Account · Pool · Window  Time``. That was readable for three rows and
worthless for twelve: the columns are not columns at all, so Account, Pool and
Window widths drift line by line and the time the user actually cares about
("how long until this one refills") is the only field NOT aligned.

This module is the ONE renderer for that queue. It is deliberately kept out of
``main.py`` (which built the blob inline) and out of
``limit_hover_card.py`` (which owns the panel, not the content), so the
independence and ordering rules below can be tested without a window.

Requirements it encodes:

* columns ``# | Account | Pool | Window | Left`` with STABLE starts — a real
  rich-text table, never repeated spaces;
* Account primary, Pool secondary, Window compact;
* ``Left`` right-aligned and ALWAYS present, even when other columns elide;
* a long Pool is truncated BEFORE ``Left`` can be pushed out;
* a header row;
* vertical scrolling for a long queue (the card caps height and scrolls);
* no per-second horizontal twitch — column widths come from the text extent,
  not from the container, and the card itself is grow-only;
* the SAME ``reset_candidates`` ordering the ↻ countdown already uses, so the
  label and this list can never disagree;
* a named-model reserve (Luna) simply appears as another Pool row.
"""

from __future__ import annotations

import html

from fastprompter.core.duration import format_remaining

#: Character budget per free-text column. Chosen so a typical
#: "Claude and GPT models" pool plus a long account name still fits the card's
#: MAX_WIDTH without the Left column being clipped.
ACCOUNT_CHARS = 22
POOL_CHARS = 20

#: Column set, in render order. ``Left`` is last on purpose: it right-aligns
#: against the card edge and can never be pushed off by a long Pool.
COLUMNS = ("#", "Account", "Pool", "Window", "Left")

#: Narrow composition (T-1298): Account and Pool stack inside ONE cell, so a
#: narrow popup keeps every essential column readable without shrinking text.
COMPACT_COLUMNS = ("#", "Account / Pool", "Window", "Left")

#: Horizontal chrome budget per cell (matches the padding-right used below).
_CELL_PADDING = 8


def _cell_texts(rows, labels):
    """Header + every cell string per column, for measurement."""
    labels = labels or {}
    header = [labels.get(col, col) for col in COLUMNS]
    body = []
    for row in rows:
        body.append([str(row["n"]), elide(row["account"], ACCOUNT_CHARS),
                     elide(row["pool"], POOL_CHARS), str(row["window"]),
                     str(row["left"])])
    return header, body


def _measure_extent(text, measure) -> int:
    try:
        return int(measure(text))
    except Exception:
        return len(str(text)) * 7


def required_width(rows, labels, measure) -> int:
    """Pixel width the WIDE table needs, measured from real text extents.

    ``measure`` is the caller's text-extent function (QFontMetrics in the
    product); the renderer stays Qt-free. Returns 0 for an empty queue.
    """
    if not rows:
        return 0
    header, body = _cell_texts(rows, labels)
    total = 0
    for index in range(len(COLUMNS)):
        widest = _measure_extent(header[index], measure)
        for cells in body:
            widest = max(widest, _measure_extent(cells[index], measure))
        total += widest + _CELL_PADDING
    return total


def elide(text: str, limit: int) -> str:
    """Truncate to ``limit`` characters with a single ellipsis."""
    text = str(text or "")
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def window_label(window, provider_id: str = "") -> str:
    """Compact window name ("5h", "Weekly", "30d", ...), pool-independent.

    The KEY wins when it names a known window: a provider may report a
    weekly-keyed window with a synthetic duration in a test or a plan quirk,
    and the key is the provider's own name for the window. Duration is the
    fallback for the generic ``window_<n>m`` keys.
    """
    from fastprompter.core.usage_limits.model import (
        FIVE_HOUR,
        MONTHLY,
        WEEKLY,
        base_key,
    )
    key = base_key(getattr(window, "key", "") or "")
    if key == FIVE_HOUR:
        # Claude calls its five-hour-keyed bucket "Current session"; the
        # authoritative reset can be more than five hours away.
        return "Session" if provider_id == "claude" else "5h"
    if key == WEEKLY:
        return "Weekly"
    if key == MONTHLY:
        return "Monthly"
    mins = getattr(window, "duration_minutes", None)
    if isinstance(mins, (int, float)) and mins > 0:
        if mins < 60:
            return f"{int(mins)}m"
        if mins < 1440:
            return f"{int(mins / 60)}h"
        return f"{int(mins / 1440)}d"
    return key or "?"


def reset_rows(candidates, now: float, name_for, pool_colors=None) -> list[dict]:
    """One dict per reset candidate, in the SAME order they were passed in.

    The caller passes ``reset_candidates`` output verbatim, so this function
    can never re-order or re-filter the queue.
    """
    rows = []
    for index, cand in enumerate(candidates, start=1):
        window = cand.window
        account = name_for(cand.account) or ""
        pool = str(getattr(window, "group_label", "") or "")
        remaining = format_remaining(
            cand.resets_at_epoch - now, short=True, minutes=True)
        rows.append({
            "n": index,
            "account": account,
            "pool": pool,
            "window": window_label(window, cand.provider_id),
            "left": remaining,
            "provider_id": cand.provider_id,
            "color": (pool_colors or {}).get(cand.provider_id, ""),
        })
    return rows


def render_table(rows, *, header: str = "Next resets", labels=None,
                 available_width: int | None = None, measure=None) -> str:
    """Rich-text table for the reset queue: header + one structured row each.

    ``labels`` maps a canonical column name from :data:`COLUMNS` to its
    translated text (the caller owns translation, so this module stays a pure
    renderer and never imports UI language state).  Columns without a label
    keep their canonical English text; ``#`` is never translated.

    ``available_width`` + ``measure`` select the NARROW composition: when the
    wide table's real measured extent exceeds the width the card can show,
    Account and Pool stack inside one cell (``# | Account / Pool | Window |
    Left``) instead of letting the popup clip them (T-1298).  Without a
    measurement the historical wide table is rendered.
    """
    if not rows:
        return f"<b>{html.escape(header)}</b>"

    labels = labels or {}
    compact = False
    if available_width is not None and measure is not None:
        compact = required_width(rows, labels, measure) > int(available_width)

    parts = [
        f"<div style='margin-bottom:3px;'><b>{html.escape(header)}</b></div>",
        "<table cellspacing='0' cellpadding='1' "
        "style='border-collapse:collapse;'>",
    ]

    if compact:
        cell_labels = {
            "#": "#",
            "Account / Pool": (labels.get("Account", "Account") + " / "
                               + labels.get("Pool", "Pool")),
            "Window": labels.get("Window", "Window"),
            "Left": labels.get("Left", "Left"),
        }
        header_cells = "".join(
            f"<td style='color:#8f856c; font-size:10px; padding-right:8px; "
            f"{'text-align:right;' if col == 'Left' else ''}'>"
            f"{html.escape(cell_labels[col])}</td>"
            for col in COMPACT_COLUMNS
        )
        parts.append(f"<tr>{header_cells}</tr>")
        for row in rows:
            color = row.get("color") or ""
            name_style = f"color:{color};" if color else ""
            account = html.escape(elide(row["account"], ACCOUNT_CHARS))
            pool = html.escape(elide(row["pool"], POOL_CHARS))
            combined = f"<span style='{name_style} white-space:nowrap;'>{account}</span>"
            if pool:
                combined += ("<br/><span style='color:#8f856c; "
                             "font-size:10px; white-space:nowrap;'>"
                             f"{pool}</span>")
            parts.append(
                "<tr>"
                f"<td style='color:#77705d; padding-right:6px;'>{row['n']}.</td>"
                f"<td style='padding-right:8px;'>{combined}</td>"
                f"<td style='color:#d8ccaa; padding-right:8px; "
                f"white-space:nowrap;'>{html.escape(row['window'])}</td>"
                f"<td style='color:#d8ccaa; font-weight:bold; "
                f"text-align:right; white-space:nowrap;'>"
                f"{html.escape(row['left'])}</td>"
                "</tr>"
            )
        parts.append("</table>")
        return "".join(parts)

    header_cells = "".join(
        f"<td style='color:#8f856c; font-size:10px; padding-right:8px; "
        f"{'text-align:right;' if col == 'Left' else ''}'>"
        f"{html.escape(labels.get(col, col))}</td>"
        for col in COLUMNS
    )
    parts.append(f"<tr>{header_cells}</tr>")

    for row in rows:
        color = row.get("color") or ""
        name_style = f"color:{color};" if color else ""
        account = html.escape(elide(row["account"], ACCOUNT_CHARS))
        pool = html.escape(elide(row["pool"], POOL_CHARS))
        parts.append(
            "<tr>"
            f"<td style='color:#77705d; padding-right:6px;'>{row['n']}.</td>"
            f"<td style='{name_style} padding-right:8px; "
            f"white-space:nowrap;'>{account}</td>"
            f"<td style='color:#8f856c; padding-right:8px; "
            f"white-space:nowrap;'>{pool}</td>"
            f"<td style='color:#d8ccaa; padding-right:8px; "
            f"white-space:nowrap;'>{html.escape(row['window'])}</td>"
            f"<td style='color:#d8ccaa; font-weight:bold; "
            f"text-align:right; white-space:nowrap;'>{html.escape(row['left'])}</td>"
            "</tr>"
        )
    parts.append("</table>")
    return "".join(parts)
