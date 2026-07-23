import os

filepath = 'src/fastprompter/ui/editor.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'tr("Prompt Queue\tAlt+Shift+C", lang)',
    'tr("Prompt Queue (All Silos)\tAlt+Shift+C", lang)'
)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated editor.py menu label with (All Silos)")
