"""Structured column layout for the reset-queue hover (T-1279 / T-1457-A).

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

* columns ``# | Account | Pool | Window | Left | Resets`` with STABLE starts —
  a real rich-text table, never repeated spaces. The SIXTH column carries the
  ABSOLUTE reset instant (clock time / weekday), because "Left" alone answers
  "how long" and never "when": a user planning the next hour needs to know
  whether the refill lands at 14:05 or at 06:00 tomorrow, and a relative
  countdown cannot tell those apart. Both time facts sit side by side, and the
  absolute one is stable across the once-per-second refresh while the relative
  one ticks down.
* Account primary, Pool secondary, Window compact;
* ``Left`` right-aligned and ALWAYS present, even when other columns elide;
* a long Pool is truncated BEFORE ``Left`` can be pushed out;
* a header row;
* vertical scrolling for a long queue (the card caps height and scrolls);
* no per-second horizontal twitch — column widths come from the text extent,
  not from the container, and the card itself is grow-only;
* the SAME ``reset_candidates`` ordering the ↻ countdown already uses, so the
  label and this list can never disagree;
* a named-model reserve (Luna) simply appears as another Pool row;
* a missing/unusable reset instant degrades to an em-dash, never to a bogus
  date or a blank column.
"""

from __future__ import annotations

import datetime
import html

from fastprompter.core.duration import format_remaining

#: Character budget per free-text column. Chosen so a typical
#: "Claude and GPT models" pool plus a long account name still fits the card's
#: MAX_WIDTH without the Left column being clipped.
ACCOUNT_CHARS = 22
POOL_CHARS = 20

#: Column set, in render order. ``Left`` is last-but-one and ``Resets`` last:
#: the two time facts belong together, ``Left`` right-aligned against the card
#: edge (it can never be pushed off by a long Pool) and the ABSOLUTE reset
#: instant to its right, which is where a reader's eye lands after the
#: countdown. T-1457-A restored the sixth column: a relative countdown alone
#: cannot tell "14:05 today" from "06:00 tomorrow" apart.
COLUMNS = ("#", "Account", "Pool", "Window", "Left", "Resets")

#: Narrow composition (T-1298): Account and Pool stack inside ONE cell, so a
#: narrow popup keeps every essential column readable without shrinking text.
#: ``Resets`` survives here too — it is the one field that cannot be recovered
#: from the others, so the fallback keeps all six facts in four cells.
COMPACT_COLUMNS = ("#", "Account / Pool", "Window", "Left", "Resets")

#: Horizontal chrome budget per cell (matches the padding-right used below).
_CELL_PADDING = 8

#: Shown when the account carries no usable reset instant. An em-dash is the
#: honest answer: it says "unknown here" without inventing a date, and it keeps
#: the column's start position stable for every other row.
MISSING_MOMENT = "—"

#: Weekday prefix for the absolute reset column. Localized labels live in the
#: i18n packs ("Weekday %d %b at %s"); the caller passes ``moment_format``.
_WEEKDAY_FORMAT = "%a %H:%M"
_SAME_DAY_FORMAT = "%H:%M"


def moment_label(epoch, now: float | None = None, ampm: bool = False) -> str:
    """Absolute reset instant for the sixth column: "14:05" / "Tue 06:00".

    Same-day resets collapse to the clock time (the weekday adds nothing the
    Header already shows), and anything further out carries its weekday so two
    candidates whose countdowns look similar read as different days. A
    missing, unusable or out-of-range epoch returns the em-dash placeholder:
    a queue row must never claim a reset instant it does not have.

    ``now`` is the same ``now`` the relative countdown is computed from, so the
    two time columns are always about the same instant and can never disagree.
    """
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool) \
            or epoch <= 0:
        return MISSING_MOMENT
    try:
        moment = datetime.datetime.fromtimestamp(float(epoch))
    except (OverflowError, OSError, ValueError):
        return MISSING_MOMENT
    if now is not None:
        try:
            today = datetime.datetime.fromtimestamp(float(now)).date()
        except (OverflowError, OSError, ValueError):
            today = datetime.datetime.now().date()
    else:
        today = datetime.datetime.now().date()
    fmt = _SAME_DAY_FORMAT if (moment.date() == today and not ampm) \
        else _WEEKDAY_FORMAT
    try:
        return moment.strftime(fmt)
    except (ValueError, OverflowError):
        return MISSING_MOMENT


def _cell_texts(rows, labels):
    """Header + every cell string per column, for measurement."""
    labels = labels or {}
    header = [labels.get(col, col) for col in COLUMNS]
    body = []
    for row in rows:
        body.append([str(row["n"]), elide(row["account"], ACCOUNT_CHARS),
                     elide(row["pool"], POOL_CHARS), str(row["window"]),
                     str(row["left"]),
                     str(row.get("resets") or MISSING_MOMENT)])
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

    Each row carries BOTH time facts about the SAME epoch: ``left`` (relative
    countdown) and ``resets`` (absolute clock instant). They are derived from
    one epoch and one ``now``, so the two columns can never describe different
    moments — which is the exact failure a hand-maintained pair of strings
    would eventually have.
    """
    rows = []
    for index, cand in enumerate(candidates, start=1):
        window = cand.window
        account = name_for(cand.account) or ""
        pool = str(getattr(window, "group_label", "") or "")
        epoch = getattr(cand, "resets_at_epoch", None)
        remaining = format_remaining(epoch - now, short=True, minutes=True)
        rows.append({
            "n": index,
            "account": account,
            "pool": pool,
            "window": window_label(window, cand.provider_id),
            "left": remaining,
            "resets": moment_label(epoch, now),
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
    Left | Resets``) instead of letting the popup clip them (T-1298).  Without
    a measurement the historical wide table is rendered.

    Column widths are derived from measured text extents only (never from the
    container), so the FIRST render of a card and every later refresh of the
    same queue produce identical column starts: no first-open jump, no
    per-second horizontal twitch, and no column that pops into existence only
    after the second render.
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
            "Resets": labels.get("Resets", "Resets"),
        }
        header_cells = "".join(
            f"<td style='color:#8f856c; font-size:10px; padding-right:8px; "
            f"{'text-align:right;' if col in ('Left', 'Resets') else ''}'>"
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
                f"<td style='color:#d8ccaa; text-align:right; "
                f"white-space:nowrap;'>"
                f"{html.escape(str(row.get('resets') or MISSING_MOMENT))}</td>"
                "</tr>"
            )
        parts.append("</table>")
        return "".join(parts)

    header_cells = "".join(
        f"<td style='color:#8f856c; font-size:10px; padding-right:8px; "
        f"{'text-align:right;' if col in ('Left', 'Resets') else ''}'>"
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
            f"<td style='color:#d8ccaa; text-align:right; "
            f"white-space:nowrap;'>"
            f"{html.escape(str(row.get('resets') or MISSING_MOMENT))}</td>"
            "</tr>"
        )
    parts.append("</table>")
    return "".join(parts)
