import re
from PyQt6.QtGui import QColor, QIcon, QPixmap

def extract_bg(style):
    m = re.search(r"background-color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def extract_color(style):
    m = re.search(r"color:\s*(#[0-9a-fA-F]+)", style)
    return m.group(1) if m else None

def create_tray_icon(color="#8b4513"):
    pix = QPixmap(16,16)
    pix.fill(QColor(color))
    return QIcon(pix)
