import os

file1 = r"scratch\execute_saitranslate_full.py"
file2 = r"scratch\validate_saitranslate.py"

with open(file1, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    '"tr": {"code": "TR", "name": "Turkish", "name_native": "Türkçe", "flag": "🇹🇷", "gt": "tr"},',
    '"tur": {"code": "TUR", "name": "Turkish", "name_native": "Türkçe", "flag": "🇹🇷", "gt": "tr"},'
)

with open(file1, 'w', encoding='utf-8') as f:
    f.write(text)

with open(file2, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    '"tr": "TR"',
    '"tur": "TUR"'
)

with open(file2, 'w', encoding='utf-8') as f:
    f.write(text)

print("Patched saitranslate scripts for TUR.")
