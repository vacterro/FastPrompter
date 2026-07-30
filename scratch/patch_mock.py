
filepath = r"tests\test_markdown_highlighter.py"
with open(filepath, encoding='utf-8') as f:
    text = f.read()

replacement = """        self._anchor = False
        self._anchor_href = None
        self._font_point_size = None
        self._font_strike_out = False

    def setFontStrikeOut(self, enabled):
        self._font_strike_out = enabled

    def setFontPointSize(self, size):
        self._font_point_size = size"""

text = text.replace(
    '        self._anchor = False\n        self._anchor_href = None',
    replacement
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Patched test_markdown_highlighter.py")
