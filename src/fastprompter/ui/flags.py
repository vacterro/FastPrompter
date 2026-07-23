"""Tiny drawn flag icons for the language selector.

Real emoji flags (🇬🇧, 🇷🇺, …) DON'T render on Windows — Segoe UI Emoji ships
no country flags, so they degrade to bare "GB"/"RU" letter boxes. Instead we
paint each flag as a small QIcon from simple color bands / crosses / marks:
crisp, antialias-free (matches the Win95 look), and font-independent.

Approximations, not heraldry — a 18x12 chip only needs to be recognisable.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QRegion

# code -> (kind, *args). Colors are hex. Band lists may hold (hex, weight).
_SPECS: dict[str, tuple] = {
    "EN": ("cross2", "#012169", "#FFFFFF", "#C8102E"),      # UK-ish
    "RU": ("h", ["#FFFFFF", "#0039A6", "#D52B1E"]),
    "UKR": ("h", ["#0057B7", "#FFD700"]),
    "EST": ("h", ["#4891D9", "#000000", "#FFFFFF"]),
    "FRA": ("v", ["#0055A4", "#FFFFFF", "#EF4135"]),
    "SPA": ("h", [("#AA151B", 1), ("#F1BF00", 2), ("#AA151B", 1)]),
    "DE": ("h", ["#000000", "#DD0000", "#FFCE00"]),
    "IT": ("v", ["#008C45", "#F4F5F0", "#CD212A"]),
    "PT": ("v", [("#046A38", 2), ("#DA291C", 3)]),
    "NL": ("h", ["#AE1C28", "#FFFFFF", "#21468B"]),
    "PL": ("h", ["#FFFFFF", "#DC143C"]),
    "SV": ("cross", "#006AA7", "#FECC00"),
    "DA": ("cross", "#C60C30", "#FFFFFF"),
    "FI": ("cross", "#FFFFFF", "#003580"),
    "NO": ("cross2", "#EF2B2D", "#FFFFFF", "#002868"),
    "JA": ("circle", "#FFFFFF", "#BC002D"),
    "ZH": ("corner", "#DE2910", "#FFDE00"),
    "KO": ("taegeuk", "#FFFFFF", "#CD2E3A", "#0047A0"),
    "TH": ("h", [("#A51931", 1), ("#F4F5F8", 1), ("#2D2A4A", 2),
                 ("#F4F5F8", 1), ("#A51931", 1)]),
    "VI": ("center", "#DA251D", "#FFFF00"),
    "AR": ("solidbar", "#006C35", "#FFFFFF"),
    "HE": ("israel", "#FFFFFF", "#0038B8"),
    # DED (grandpa) has no country — a dark-gold banner in the app's colors.
    # DED (grandpa) has no country — a dark-gold banner in the app's colors.
    "DED": ("solidbar", "#3a2a12", "#D9B340"),
    "TUR": ("center", "#E30A17", "#FFFFFF"),
    "HI": ("h", ["#FF9933", "#FFFFFF", "#128807"]),
    "ID": ("h", ["#CE1126", "#FFFFFF"]),
    "EL": ("h", [("#0D5EAF", 1), ("#FFFFFF", 1), ("#0D5EAF", 1), ("#FFFFFF", 1), ("#0D5EAF", 1)]),
    "CS": ("h", [("#FFFFFF", 1), ("#D7141A", 1)]),
    "RO": ("v", ["#002B7F", "#FCD116", "#CE1126"]),
    "HU": ("h", ["#CD2A3E", "#FFFFFF", "#436F4D"]),
    "BG": ("h", ["#FFFFFF", "#00966E", "#D62612"]),
    "SK": ("h", [("#FFFFFF", 1), ("#0B4EA2", 1), ("#EE1C25", 1)]),
    "HR": ("h", ["#FF0000", "#FFFFFF", "#171796"]),
}


def _bands(p, w, h, colors, vertical=False):
    specs = [(c, 1) if isinstance(c, str) else c for c in colors]
    total = sum(wt for _, wt in specs) or 1
    pos = 0
    for i, (hexc, wt) in enumerate(specs):
        run = (w if vertical else h) - pos if i == len(specs) - 1 \
            else round((w if vertical else h) * wt / total)
        rect = QRect(pos, 0, run, h) if vertical else QRect(0, pos, w, run)
        p.fillRect(rect, QColor(hexc))
        pos += run


def _cross(p, w, h, bg, cross, inner=None):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    cx, cy, tw = int(w * 0.32), int(h * 0.42), max(2, h // 5)
    p.fillRect(QRect(cx, 0, tw, h), QColor(cross))
    p.fillRect(QRect(0, cy, w, tw), QColor(cross))
    if inner:
        iw = max(1, tw // 2)
        off = (tw - iw) // 2
        p.fillRect(QRect(cx + off, 0, iw, h), QColor(inner))
        p.fillRect(QRect(0, cy + off, w, iw), QColor(inner))


def _circle(p, w, h, bg, circ):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    r = int(h * 0.34)
    p.setBrush(QColor(circ))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(w // 2 - r, h // 2 - r, 2 * r, 2 * r)


def _taegeuk(p, w, h, bg, top, bot):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    r, cx, cy = int(h * 0.34), w // 2, h // 2
    p.setClipRegion(QRegion(QRect(cx - r, cy - r, 2 * r, 2 * r), QRegion.RegionType.Ellipse))
    p.fillRect(QRect(0, 0, w, cy), QColor(top))
    p.fillRect(QRect(0, cy, w, h - cy), QColor(bot))
    p.setClipping(False)


def _corner(p, w, h, bg, mark):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    s = max(3, h // 3)
    p.fillRect(QRect(2, 2, s, s), QColor(mark))


def _center(p, w, h, bg, mark):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    s = max(3, h // 2)
    p.fillRect(QRect((w - s) // 2, (h - s) // 2, s, s), QColor(mark))


def _solidbar(p, w, h, bg, bar):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    bh = max(2, h // 4)
    p.fillRect(QRect(0, (h - bh) // 2, w, bh), QColor(bar))


def _israel(p, w, h, bg, blue):
    p.fillRect(QRect(0, 0, w, h), QColor(bg))
    sh = max(2, h // 6)
    p.fillRect(QRect(0, sh, w, sh), QColor(blue))
    p.fillRect(QRect(0, h - 2 * sh, w, sh), QColor(blue))
    s = max(3, h // 3)
    p.fillRect(QRect((w - s) // 2, (h - s) // 2, s, s), QColor(blue))


def flag_icon(code, w=18, h=12):
    """Return a QIcon flag for a language code, or None if we have no spec."""
    spec = _SPECS.get(code)
    if not spec:
        return None
    pm = QPixmap(w, h)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        kind, args = spec[0], spec[1:]
        if kind == "h":
            _bands(p, w, h, args[0], vertical=False)
        elif kind == "v":
            _bands(p, w, h, args[0], vertical=True)
        elif kind == "cross":
            _cross(p, w, h, *args)
        elif kind == "cross2":
            _cross(p, w, h, args[0], args[1], args[2])
        elif kind == "circle":
            _circle(p, w, h, *args)
        elif kind == "taegeuk":
            _taegeuk(p, w, h, *args)
        elif kind == "corner":
            _corner(p, w, h, *args)
        elif kind == "center":
            _center(p, w, h, *args)
        elif kind == "solidbar":
            _solidbar(p, w, h, *args)
        elif kind == "israel":
            _israel(p, w, h, *args)
        p.setPen(QColor("#3a3a3a"))
        p.drawRect(0, 0, w - 1, h - 1)
    finally:
        p.end()
    return QIcon(pm)
