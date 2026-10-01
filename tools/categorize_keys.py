import json
import re
from pathlib import Path

root = Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter")
ref = json.loads((root / "build/reference_703.json").read_text(encoding="utf-8"))

print(f"Total keys: {len(ref)}")

# Check keys by length
short = [k for k in ref if len(k) <= 15]
medium = [k for k in ref if 15 < len(k) <= 60]
long_k = [k for k in ref if len(k) > 60]

print(f"Short keys (<=15 chars): {len(short)}")
print(f"Medium keys (16-60 chars): {len(medium)}")
print(f"Long keys (>60 chars): {len(long_k)}")
