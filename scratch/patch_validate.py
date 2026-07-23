import os

file2 = r"scratch\validate_saitranslate.py"

with open(file2, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    '"th", "tr",',
    '"th", "tur",'
)

with open(file2, 'w', encoding='utf-8') as f:
    f.write(text)

print("Patched validate_saitranslate.py for tur.")
