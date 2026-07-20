"""Build complete French translation from EN master + existing FRA."""
import re
import ast

# Read EN file
with open(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py", encoding="utf-8") as f:
    en_text = f.read()

# Read FRA file
with open(r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\fra.py", encoding="utf-8") as f:
    fra_text = f.read()

# Extract dict literal from both files
en_match = re.search(r'TRANSLATIONS\s*:\s*dict\[str, str\]\s*=\s*(\{.*\})', en_text, re.DOTALL)
fra_match = re.search(r'TRANSLATIONS\s*:\s*dict\[str, str\]\s*=\s*(\{.*\})', fra_text, re.DOTALL)

en_dict = ast.literal_eval(en_match.group(1))
fra_dict = ast.literal_eval(fra_match.group(1))

en_keys = set(en_dict.keys())
fra_keys = set(fra_dict.keys())
missing = en_keys - fra_keys
extra = fra_keys - en_keys

print(f"EN keys: {len(en_keys)}")
print(f"FRA keys: {len(fra_keys)}")
print(f"Missing keys to translate: {len(missing)}")
print(f"Extra keys in FRA not in EN: {len(extra)}")

if extra:
    print(f"\nExtra keys: {sorted(extra)}")

print("\n=== MISSING KEYS ===")
with open(r"V:\_TEMP_\opencode\missing_keys.txt", "w", encoding="utf-8") as out:
    for k in sorted(missing):
        out.write(repr(k) + "\n")
print(f"Written to missing_keys.txt")
