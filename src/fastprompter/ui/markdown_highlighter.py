import re

from PyQt6 import sip
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextFormat

# Block-state bit layout (block.userState is shared with the editor's
# margin marks): bits 0-7 = margin mark (0-3), bit 8 = inside code fence.
CODE_BIT = 1 << 8
MARK_MASK = 0xFF

# Universal keyword set covering the popular languages (Python, JS/TS,
# C/C++/C#, Java, Go, Rust, PHP, Ruby, SQL, Bash, PowerShell...)
_CODE_KEYWORDS = (
    "def|class|import|from|return|if|elif|else|for|while|try|except|finally|"
    "with|as|pass|break|continue|lambda|yield|async|await|raise|assert|"
    "function|var|let|const|new|this|typeof|instanceof|export|default|"
    "public|private|protected|static|void|int|float|double|bool|boolean|"
    "string|char|long|short|struct|enum|interface|extends|implements|"
    "namespace|using|template|typename|virtual|override|switch|case|do|"
    "goto|sizeof|null|nullptr|None|true|false|True|False|nil|fn|impl|mut|"
    "match|trait|package|func|go|defer|chan|select|SELECT|FROM|WHERE|"
    "INSERT|UPDATE|DELETE|JOIN|echo|print|println|printf|console"
)


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None, base_font_size=11):
        super().__init__(parent)
        self.base_font_size = base_font_size
        self.theme = None
        self._highlighting_rules = []
        self._skip_highlighting = False

        self._setup_rules()

    def update_base_size(self, size):
        self.base_font_size = size
        self._setup_rules()
        self.rehighlight()

    def update_theme(self, theme):
        self.theme = theme
        self._setup_rules()
        self.rehighlight()

    def set_skip_large(self, skip):
        self._skip_highlighting = skip

    def _setup_rules(self):
        self._highlighting_rules.clear()

        # Bold: **text**
        bold_format = QTextCharFormat()
        bold_format.setFontWeight(QFont.Weight.Bold)
        self._highlighting_rules.append((re.compile(r'\*\*.*?\*\*'), bold_format))

        # Underline: __text__ (checked before single-underscore italic)
        underline_format = QTextCharFormat()
        underline_format.setFontUnderline(True)
        self._highlighting_rules.append((re.compile(r'__[^_\n]+__'), underline_format))

        # Strikethrough: ~~text~~
        strike_format = QTextCharFormat()
        strike_format.setFontStrikeOut(True)
        self._highlighting_rules.append((re.compile(r'~~[^~\n]+~~'), strike_format))

        # Italic: *text* or _text_ (single markers only)
        italic_format = QTextCharFormat()
        italic_format.setFontItalic(True)
        self._highlighting_rules.append((re.compile(r'\*(?!\*).*?\*(?!\*)'), italic_format))
        self._highlighting_rules.append((re.compile(r'(?<!_)_(?!_)[^_\n]+(?<!_)_(?!_)'), italic_format))

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

        # Inline Code: `text`
        code_format = QTextCharFormat()
        code_format.setFontFamily("Consolas")
        code_format.setBackground(QColor("#1a1a1a"))
        code_format.setForeground(QColor("#e06c75"))
        self._highlighting_rules.append((re.compile(r'`[^`]+`'), code_format))

        # Blockquote: > text
        quote_format = QTextCharFormat()
        quote_format.setForeground(QColor("#7f848e"))
        quote_format.setFontItalic(True)
        self._highlighting_rules.append((re.compile(r'^>\s+.*'), quote_format))

        # Links: [text](url) — clickable via anchor href
        link_format = QTextCharFormat()
        link_format.setForeground(QColor("#61afef"))
        link_format.setFontUnderline(True)
        link_format.setAnchor(True)
        self._link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        self._highlighting_rules.append((self._link_pattern, link_format))

        # Horizontal Rule: ---
        hr_format = QTextCharFormat()
        hr_format.setForeground(QColor("#5a4a2a"))
        hr_format.setFontWeight(QFont.Weight.Bold)
        self._highlighting_rules.append((re.compile(r'^\s*[-*_]{3,}\s*$'), hr_format))

        # Checkbox unchecked: [ ] — make invisible (painted by editor)
        cb_unchecked = QTextCharFormat()
        cb_unchecked.setForeground(QColor(0, 0, 0, 0))
        self._highlighting_rules.append((re.compile(r'^\s*\[\s\]\s'), cb_unchecked))

        # Checkbox checked: [x] — make invisible (painted by editor)
        cb_checked = QTextCharFormat()
        cb_checked.setForeground(QColor(0, 0, 0, 0))
        self._highlighting_rules.append((re.compile(r'^\s*\[[xX]\]\s'), cb_checked))

        # --- Fenced code blocks: monospace + panel background ---
        def _code_fmt(color):
            fmt = QTextCharFormat()
            fmt.setFontFamily("Consolas")
            fmt.setFontFixedPitch(True)
            fmt.setBackground(QColor("#161616"))
            fmt.setForeground(QColor(color))
            return fmt

        self._code_block_format = _code_fmt("#c8ccd4")
        self._code_fence_format = _code_fmt("#5f6672")
        self._code_sub_rules = [
            (re.compile(r'(#|//).*$'), _code_fmt("#7f848e")),          # comments
            (re.compile(r'"[^"\n]*"|\'[^\'\n]*\''), _code_fmt("#98c379")),  # strings
            (re.compile(r'\b\d+(\.\d+)?\b'), _code_fmt("#d19a66")),   # numbers
            (re.compile(r'\b(?:' + _CODE_KEYWORDS + r')\b'), _code_fmt("#c678dd")),
        ]

        # Lists (Bullets and Numbers)
        list_format = QTextCharFormat()
        list_format.setForeground(QColor("#D9B340"))
        self._highlighting_rules.append((re.compile(r'^\s*[-*•+]\s+'), list_format))
        self._highlighting_rules.append((re.compile(r'^\s*\d+\.\s+'), list_format))

    def highlightBlock(self, text):
        if self._skip_highlighting or sip.isdeleted(self): return

        # Preserve the editor's margin-mark bits while tracking fences
        prev_in_code = bool(max(0, self.previousBlockState()) & CODE_BIT)
        mark_bits = max(0, self.currentBlockState()) & MARK_MASK
        is_fence = text.strip().startswith("```")

        if prev_in_code:
            if is_fence:
                # closing fence: code region ends after this line
                self.setCurrentBlockState(mark_bits)
                self.setFormat(0, len(text), self._code_fence_format)
            else:
                self.setCurrentBlockState(mark_bits | CODE_BIT)
                self.setFormat(0, len(text), self._code_block_format)
                for pattern, fmt in self._code_sub_rules:
                    for match in pattern.finditer(text):
                        self.setFormat(match.start(), match.end() - match.start(), fmt)
            return
        if is_fence:
            # opening fence (``` or ```lang)
            self.setCurrentBlockState(mark_bits | CODE_BIT)
            self.setFormat(0, len(text), self._code_fence_format)
            return
        self.setCurrentBlockState(mark_bits)

        for pattern, format in self._highlighting_rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), format)
                if format.isAnchor():
                    url_match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', match.group())
                    if url_match:
                        link_fmt = QTextCharFormat()
                        link_fmt.setAnchor(True)
                        link_fmt.setAnchorHref(url_match.group(2))
                        link_fmt.setForeground(QColor("#61afef"))
                        link_fmt.setFontUnderline(True)
                        self.setFormat(match.start(), match.end() - match.start(), link_fmt)
