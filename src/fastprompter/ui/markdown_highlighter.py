import re

from PyQt6 import sip
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextFormat

from fastprompter.theme.themes import blend_hex

# Block-state bit layout (block.userState is shared with the editor's
# margin marks): bits 0-7 = margin mark (0-3), bit 8 = inside code fence,
# bit 9 = fold anchor is collapsed, bits 10-11 = watcher queue state.
# Everything but the code-fence bit is owned by the editor and preserved
# here - a bit missing from _KEEP_MASK is silently wiped on the next
# rehighlight, which looks like the feature losing its own state at random.
CODE_BIT = 1 << 8
FOLD_BIT = 1 << 9
QUEUED_BIT = 1 << 10       # this line is sitting in a prompt queue
SENT_BIT = 1 << 11         # ...and it has been sent
MARK_MASK = 0xFF
_KEEP_MASK = MARK_MASK | FOLD_BIT | QUEUED_BIT | SENT_BIT

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
        # None = use Consolas for code. Set to a family name to render code
        # in the editor's own font instead (user asked for Verdana-or-their
        # own font rather than forced monospace).
        self.code_font_family = None
        self._highlighting_rules = []
        self._skip_highlighting = False
        # Degraded mode for large documents: keep the essentials (headers,
        # links, bare URLs, basic formatting) but skip the expensive fenced
        # code sub-highlighting and the conceal extras. Replaces the old
        # all-or-nothing >500 skip that made headers vanish entirely.
        self._degraded = False
        self.hr_as_line = False   # when True, --- text is hidden (painted as a visual line)
        # Obsidian-style Live Preview: the emphasis markers themselves are
        # hidden so the text reads as rendered, and reappear on the block the
        # caret is in so it stays editable. reveal_block is the caret's block
        # number, kept up to date by the editor.
        self.conceal = False
        self.reveal_block = -1
        # same technique the `---` rule uses: a char format cannot delete
        # glyphs, so shrink them to 1pt and paint them fully transparent
        self._hidden_format = QTextCharFormat()
        self._hidden_format.setForeground(QColor(0, 0, 0, 0))
        self._hidden_format.setFontPointSize(1)

        self._setup_rules()

    def update_base_size(self, size):
        self.base_font_size = size
        self._setup_rules()
        self.rehighlight()

    def update_theme(self, theme):
        self.theme = theme
        self._setup_rules()
        self.rehighlight()

    def update_code_font(self, family):
        """Font for inline code and fenced blocks. None/'' -> Consolas."""
        self.code_font_family = family or None
        self._setup_rules()
        self.rehighlight()

    # (pattern, left marker width, right marker width)
    _CONCEAL_RULES = (
        (re.compile(r'\*\*[^*\n]+\*\*'), 2, 2),
        (re.compile(r'(?<!\*)\*(?!\*)[^*\n]+\*(?!\*)'), 1, 1),
        (re.compile(r'__[^_\n]+__'), 2, 2),
        (re.compile(r'~~[^~\n]+~~'), 2, 2),
        (re.compile(r'(?<!`)`(?!`)[^`\n]+`(?!`)'), 1, 1),
    )

    def set_conceal(self, enable):
        self.conceal = bool(enable)
        self.rehighlight()

    def set_reveal_block(self, block_number):
        """Move the revealed block, repainting only the two blocks involved.

        A full rehighlight on every caret move is far too expensive on a long
        document, and this fires on every arrow key."""
        old = self.reveal_block
        if old == block_number:
            return
        self.reveal_block = block_number
        doc = self.document()
        if doc is None or sip.isdeleted(doc):
            return
        for n in (old, block_number):
            if n is None or n < 0:
                continue
            blk = doc.findBlockByNumber(n)
            if blk.isValid():
                self.rehighlightBlock(blk)

    def update_hr_as_line(self, enable):
        self.hr_as_line = enable
        self._setup_rules()
        self.rehighlight()

    def set_skip_large(self, skip):
        # Kept for call-site compatibility: a "large" document now degrades
        # (essentials only) rather than turning highlighting fully off.
        self.set_degraded(bool(skip))

    def set_degraded(self, degraded):
        """Large-document mode: essentials kept, expensive work skipped.

        Unlike the old skip guard this never blanks headers/links/URLs — it
        only drops fenced-code sub-highlighting and conceal extras.
        """
        self._degraded = bool(degraded)

    def _theme_color(self, key, fallback):
        """Read one key out of the active theme's raw_colors.

        update_theme() used to store the theme and _setup_rules() never read
        it back, so headers/links/bullets rendered fixed gold on every theme.
        """
        try:
            raw = (self.theme or {}).get("raw_colors") or {}
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val
        except Exception:
            pass
        return fallback

    def _setup_rules(self):
        self._highlighting_rules.clear()
        accent = self._theme_color("accent", "#D9B340")
        text_main = self._theme_color("text_main", "#c0c0c0")
        bg_text = self._theme_color("bg_text", "#2c2c2c")
        quote_color = blend_hex(text_main, bg_text, 0.45)
        code_family = self.code_font_family or "Consolas"

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
        # The content must not contain the marker itself, and the opening
        # marker must not sit next to a twin. The old `\*(?!\*).*?\*(?!\*)`
        # matched INSIDE **bold**: it started on the second star and let
        # `.*?` run to `bold*`, so the italic rule (applied later) replaced
        # the bold weight and bold rendered as italic.
        self._highlighting_rules.append((re.compile(r'(?<!\*)\*(?!\*)[^*\n]+\*(?!\*)'), italic_format))
        # `_` is NOT emphasis inside a word — CommonMark says so precisely
        # because identifiers exist: `chest_open: … chest_closed` italicised
        # everything between the two underscores, and so did every
        # snake_case name, file path and __dunder__ in a note. Asterisks keep
        # their intraword behaviour (`in*ter*nal` is still italic) — that is
        # the same carve-out the spec makes.
        # Fixed: exclude alphanumeric before/after, not underscore itself
        self._highlighting_rules.append(
            (re.compile(r'(?<![a-zA-Z0-9])_(?!_)[^_\n]+(?<!_)_(?![a-zA-Z0-9])'), italic_format))

        # Header 1: # Text
        h1_format = QTextCharFormat()
        h1_format.setFontWeight(QFont.Weight.Bold)
        h1_format.setProperty(QTextFormat.Property.FontPointSize, self.base_font_size * 1.5)
        h1_format.setForeground(QColor(accent))
        self._highlighting_rules.append((re.compile(r'^#\s+.*'), h1_format))

        # Header 2: ## Text
        h2_format = QTextCharFormat()
        h2_format.setFontWeight(QFont.Weight.Bold)
        h2_format.setProperty(QTextFormat.Property.FontPointSize, self.base_font_size * 1.3)
        h2_format.setForeground(QColor(accent))
        self._highlighting_rules.append((re.compile(r'^##\s+.*'), h2_format))

        # Header 3: ### Text
        h3_format = QTextCharFormat()
        h3_format.setFontWeight(QFont.Weight.Bold)
        h3_format.setProperty(QTextFormat.Property.FontPointSize, self.base_font_size * 1.1)
        h3_format.setForeground(QColor(accent))
        self._highlighting_rules.append((re.compile(r'^###\s+.*'), h3_format))

        # Hashtags: #tag (never "# Header" - that needs a space after the
        # hash, which is exactly what tells the two apart). Rendered as a
        # quiet link rather than a loud badge: it is part of the sentence.
        from fastprompter.core.hashtags import TAG_RE

        tag_format = QTextCharFormat()
        tag_format.setForeground(QColor(blend_hex(accent, text_main, 0.25)))
        tag_format.setFontUnderline(True)
        self._highlighting_rules.append((TAG_RE, tag_format))

        # Inline Code: `text`
        code_format = QTextCharFormat()
        code_format.setFontFamily(code_family)
        code_format.setBackground(QColor("#1a1a1a"))
        code_format.setForeground(QColor("#e06c75"))
        self._highlighting_rules.append((re.compile(r'`[^`]+`'), code_format))

        # Blockquote: > text
        quote_format = QTextCharFormat()
        quote_format.setForeground(QColor(quote_color))
        quote_format.setFontItalic(True)
        self._highlighting_rules.append((re.compile(r'^>\s+.*'), quote_format))

        # Links: [text](url) — clickable via anchor href
        link_format = QTextCharFormat()
        link_format.setForeground(QColor("#61afef"))
        link_format.setFontUnderline(True)
        link_format.setAnchor(True)
        self._link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        self._highlighting_rules.append((self._link_pattern, link_format))

        # Bare http(s) URLs — clickable without markdown syntax. The lookbehind
        # skips the URL inside [text](url), which the rule above owns.
        url_format = QTextCharFormat()
        url_format.setForeground(QColor("#61afef"))
        url_format.setFontUnderline(True)
        url_format.setAnchor(True)
        self._url_pattern = re.compile(r'(?<![\w(])https?://[^\s<>"\')\]]+')
        self._highlighting_rules.append((self._url_pattern, url_format))

        # Markdown Images: ![alt](url) — visually collapse to a tiny invisible dot
        # 1. The '!' keeps normal height (preventing vertical overlap) and gets 150px letter spacing
        #    to guarantee minimum width for the drawn pill.
        img_format_first = QTextCharFormat()
        img_format_first.setForeground(QColor(0, 0, 0, 0))
        img_format_first.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
        img_format_first.setFontLetterSpacing(150.0)
        self._highlighting_rules.append((re.compile(r'!(?=\[.*?\]\(.*?\))'), img_format_first))

        # 2. The rest of the string gets 1pt font to minimize extra width.
        img_format_rest = QTextCharFormat()
        img_format_rest.setForeground(QColor(0, 0, 0, 0))
        img_format_rest.setFontPointSize(1)
        self._highlighting_rules.append((re.compile(r'(?<=!)\[.*?\]\((.*?)\)'), img_format_rest))

        # Horizontal Rule: ---
        hr_format = QTextCharFormat()
        if self.hr_as_line:
            # editor paints the line; hide the raw --- text
            hr_format.setForeground(QColor(0, 0, 0, 0))
            hr_format.setFontPointSize(1)
        else:
            hr_format.setForeground(QColor(self._theme_color("border_light", "#5a4a2a")))
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
            fmt.setFontFamily(code_family)
            fmt.setFontFixedPitch(self.code_font_family is None)
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
        list_format.setForeground(QColor(accent))
        self._highlighting_rules.append((re.compile(r'^\s*[-*•+]\s+'), list_format))
        self._highlighting_rules.append((re.compile(r'^\s*\d+\.\s+'), list_format))

        strat = QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias
        for _, fmt in self._highlighting_rules:
            fmt.setFontStyleStrategy(strat)
        self._code_block_format.setFontStyleStrategy(strat)
        self._code_fence_format.setFontStyleStrategy(strat)
        for _, fmt in self._code_sub_rules:
            fmt.setFontStyleStrategy(strat)

    def highlightBlock(self, text):
        if self._skip_highlighting or sip.isdeleted(self): return

        # Preserve the editor's margin-mark bits while tracking fences
        prev_in_code = bool(max(0, self.previousBlockState()) & CODE_BIT)
        mark_bits = max(0, self.currentBlockState()) & _KEEP_MASK
        stripped = text.strip()
        is_fence = stripped.startswith("```")
        # A closing fence is ``` with optional whitespace only (no info
        # string).  An opening fence may carry a language tag after ```.
        # Treating ```python as a closer was the root cause of state leaks:
        # the code region would end prematurely, and every block after it
        # inherited the wrong state.
        is_closer = is_fence and stripped.rstrip("`") == ""

        if prev_in_code:
            if is_closer:
                # closing fence: code region ends after this line
                self.setCurrentBlockState(mark_bits)
                self.setFormat(0, len(text), self._code_fence_format)
            else:
                self.setCurrentBlockState(mark_bits | CODE_BIT)
                if is_fence:
                    # nested ``` with info string inside code — format as
                    # fence but stay in code
                    self.setFormat(0, len(text), self._code_fence_format)
                else:
                    self.setFormat(0, len(text), self._code_block_format)
                    if not self._degraded:
                        for pattern, fmt in self._code_sub_rules:
                            for match in pattern.finditer(text):
                                self.setFormat(match.start(),
                                               match.end() - match.start(), fmt)
            return
        if is_fence:
            # opening fence (``` or ```lang)
            self.setCurrentBlockState(mark_bits | CODE_BIT)
            self.setFormat(0, len(text), self._code_fence_format)
            return
        self.setCurrentBlockState(mark_bits)

        for pattern, format in self._highlighting_rules:
            for match in pattern.finditer(text):
                start, length = match.start(), match.end() - match.start()
                if format.isAnchor():
                    url_match = self._link_pattern.match(match.group())
                    if url_match:
                        link_fmt = QTextCharFormat(format)
                        link_fmt.setAnchorHref(url_match.group(2))
                        self._apply(start, length, link_fmt)
                    else:
                        url_match = self._url_pattern.match(match.group())
                        if url_match:
                            link_fmt = QTextCharFormat(format)
                            link_fmt.setAnchorHref(url_match.group(0))
                            self._apply(start, length, link_fmt)
                        else:
                            self._apply(start, length, format)
                else:
                    self._apply(start, length, format)

        if not self._degraded:
            self._conceal_markers(text)

    def _conceal_markers(self, text):
        """Hide the emphasis markers themselves (Obsidian-style preview).

        The caret's own block is left alone so the markup stays visible
        exactly where it is being edited. Hiding uses the same trick the
        `---` rule already uses in this file - transparent colour plus a 1pt
        size - because a QTextCharFormat cannot actually remove glyphs."""
        if not self.conceal:
            return
        if self.currentBlock().blockNumber() == self.reveal_block:
            return
        for pattern, left, right in self._CONCEAL_RULES:
            for m in pattern.finditer(text):
                if m.end() - m.start() <= left + right:
                    continue                 # nothing between the markers
                self._apply(m.start(), left, self._hidden_format)
                self._apply(m.end() - right, right, self._hidden_format)

    def _apply(self, start, length, fmt):
        """Merge a rule's format onto what is already there.

        setFormat() REPLACES the char format outright, so whichever rule ran
        last won and everything it did not set was dropped — bold inside a
        heading lost the heading, bold+italic lost the bold. Merging keeps
        the properties each rule actually cares about."""
        merged = QTextCharFormat(self.format(start))
        merged.merge(fmt)
        self.setFormat(start, length, merged)
