import os

filepath = 'src/fastprompter/ui/flags.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

new_specs = """    # DED (grandpa) has no country — a dark-gold banner in the app's colors.
    "DED": ("solidbar", "#3a2a12", "#D9B340"),
    "TUR": ("center", "#E30A17", "#FFFFFF"),
    "HI": ("h", ["#FF9933", "#FFFFFF", "#128807"]),
    "ID": ("h", ["#CE1126", "#FFFFFF"]),
    "EL": ("h", [("#0D5EAF", 1), ("#FFFFFF", 1), ("#0D5EAF", 1), ("#FFFFFF", 1), ("#0D5EAF", 1)]),
    "CS": ("h", [("#FFFFFF", 1), ("#D7141A", 1)]),
    "RO": ("v", ["#002B7F", "#FCD116", "#CE1126"]),
    "HU": ("h", ["#CD2A3E", "#FFFFFF", "#436F4D"]),
    "BG": ("h", ["#FFFFFF", "#00966E", "#D62612"]),
    "SK": ("h", [("#FFFFFF", 1), ("#0B4EA2", 1), ("#EE1C25", 1)]),
    "HR": ("h", ["#FF0000", "#FFFFFF", "#171796"]),
}"""

text = text.replace('    "DED": ("solidbar", "#3a2a12", "#D9B340"),\n}', new_specs)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated flags.py with flag specs for all 33 languages.")
