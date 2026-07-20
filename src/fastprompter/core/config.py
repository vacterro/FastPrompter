import re

from PyQt6.QtGui import QColor, QIcon, QPixmap


def extract_bg(style):
    m = re.search(r"background-color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def extract_color(style):
    # Require start-of-string, space, or semicol before "color:" to avoid matching "background-color:"
    m = re.search(r"(?:^|[ ;])color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def extract_border_color(style):
    """Extract the first hex color from a CSS border declaration.

    Handles patterns like:
      border: 1px solid #xxx
      border: 1px outset #xxx
      border: 1px inset #xxx

    Falls back to extracting border-top-color if no compact border found.
    """
    m = re.search(r"border:\s*[^#]*?(#[0-9a-fA-F]+)", style)
    if m:
        return m.group(1)
    # Fallback: border-top-color
    m = re.search(r"border-top-color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def create_tray_icon(color="#8b4513"):
    pix = QPixmap(16,16)
    pix.fill(QColor(color))
    return QIcon(pix)
