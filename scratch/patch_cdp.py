
filepath = r"src\fastprompter\core\watcher\cdp.py"
with open(filepath, encoding='utf-8') as f:
    text = f.read()

replacement = """    if title_match:
        needle = title_match.lower()
        matched = [t for t in pages if needle in str(t.get("title", "")).lower()]
        if matched:
            return matched[0]
        return None
    return pages[0]"""

text = text.replace(
    '    if title_match:\n        needle = title_match.lower()\n        matched = [t for t in pages if needle in str(t.get("title", "")).lower()]\n        if matched:\n            return matched[0]\n    return pages[0]',
    replacement
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Patched cdp.py")
