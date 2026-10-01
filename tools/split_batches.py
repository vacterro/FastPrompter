import json
from pathlib import Path

root = Path("V:/___VAC/__K/__CODE/_PY/_FastPrompter")
ref = json.loads((root / "build/reference_703.json").read_text(encoding="utf-8"))
keys = sorted(ref.keys())

def save_batch(start, end, filename):
    batch = {}
    for i in range(start, min(end, len(keys))):
        k = keys[i]
        batch[k] = {
            "idx": i,
            "ru": ref[k].get("ru", ""),
            "de": ref[k].get("de", ""),
            "est": ref[k].get("est", ""),
            "it": ref[k].get("it", "")
        }
    (root / f"build/{filename}").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {filename} with {len(batch)} keys")

save_batch(0, 175, "batch1_keys.json")
save_batch(175, 350, "batch2_keys.json")
save_batch(350, 525, "batch3_keys.json")
save_batch(525, 703, "batch4_keys.json")
