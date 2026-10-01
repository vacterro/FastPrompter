import json
from pathlib import Path

root = Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter")

hr = json.loads((root / "build/untranslated/hr.json").read_text(encoding="utf-8"))
ro = json.loads((root / "build/untranslated/ro.json").read_text(encoding="utf-8"))
el = json.loads((root / "build/untranslated/el.json").read_text(encoding="utf-8"))

print(f"hr keys: {len(hr)}")
print(f"ro keys: {len(ro)}")
print(f"el keys: {len(el)}")

all_keys = sorted(set(hr) | set(ro) | set(el))
print(f"Union of keys: {len(all_keys)}")

# Let's inspect placeholders, accelerators, newlines across all_keys
placeholders = {}
for k in all_keys:
    # find {xxx}
    import re
    braces = re.findall(r"\{[^}]*\}", k)
    percents = re.findall(r"%[0-9.]*[sdf]", k)
    amps = [m.group(0) for m in re.finditer(r"&[A-Za-z]", k)]
    if braces or percents or amps:
        placeholders[k] = {"braces": braces, "percents": percents, "amps": amps}

print(f"Keys with placeholders or accelerators: {len(placeholders)}")
