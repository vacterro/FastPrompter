
filepath = r"tests\test_markdown_highlighter.py"
with open(filepath, encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'assert len(h._highlighting_rules) == 17, (',
    'assert len(h._highlighting_rules) == 18, ('
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Patched test_markdown_highlighter.py rule count")
