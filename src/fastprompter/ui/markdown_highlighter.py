from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QFont, QColor, QTextFormat
import re

class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None, base_font_size=11):
        super().__init__(parent)
        self.base_font_size = base_font_size
        self._highlighting_rules = []

        self._setup_rules()

    def update_base_size(self, size):
        self.base_font_size = size
        self._setup_rules()
        self.rehighlight()

    def _setup_rules(self):
        self._highlighting_rules.clear()

        # Bold: **text**
        bold_format = QTextCharFormat()
        bold_format.setFontWeight(QFont.Weight.Bold)
        self._highlighting_rules.append((re.compile(r'\*\*.*?\*\*'), bold_format))

        # Italic: *text* or _text_
        italic_format = QTextCharFormat()
        italic_format.setFontItalic(True)
        self._highlighting_rules.append((re.compile(r'\*(?!\*).*?\*(?!\*)'), italic_format))
        self._highlighting_rules.append((re.compile(r'\_.*?\_'), italic_format))

        # Header 1: # Text
        h1_format = QTextCharFormat()
        h1_format.setFontWeight(QFont.Weight.Bold)
        h1_format.setProperty(QTextFormat.Property.FontPointSize, self.base_font_size * 1.5)
        h1_format.setForeground(QColor("#D9B340")) # Using the gold color
        self._highlighting_rules.append((re.compile(r'^#\s+.*'), h1_format))

        # Header 2: ## Text
        h2_format = QTextCharFormat()
        h2_format.setFontWeight(QFont.Weight.Bold)
        h2_format.setProperty(QTextFormat.Property.FontPointSize, self.base_font_size * 1.3)
        h2_format.setForeground(QColor("#D9B340"))
        self._highlighting_rules.append((re.compile(r'^##\s+.*'), h2_format))

        # Header 3: ### Text
        h3_format = QTextCharFormat()
        h3_format.setFontWeight(QFont.Weight.Bold)
        h3_format.setProperty(QTextFormat.Property.FontPointSize, self.base_font_size * 1.1)
        h3_format.setForeground(QColor("#D9B340"))
        self._highlighting_rules.append((re.compile(r'^###\s+.*'), h3_format))

    def highlightBlock(self, text):
        for pattern, format in self._highlighting_rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), format)
