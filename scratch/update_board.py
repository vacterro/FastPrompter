import os

filepath = '.saipen/BOARD.md'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("- [ ] T-211 (P2)", "- [x] T-211 (P2)")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated BOARD.md for T-211.")
