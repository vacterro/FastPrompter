"""Check the fill-in parts: key fidelity, placeholders, tabs, entities, empties."""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(".saipen/saitranslate/batches/out")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
ENTITY = re.compile(r"&(?:ndash|amp|rarr|bull|nbsp|lt|gt|quot|#\d+);")

summary = {}
problems = []
for lang in sorted({p.name.split(".")[0] for p in OUT.glob("*.part*.json")}):
    parts = sorted(OUT.glob(f"{lang}.part*.json"))
    filled = empty = bad_json = 0
    identical = []
    for part in parts:
        try:
            data = json.load(open(part, encoding="utf-8"))
        except Exception as exc:
            bad_json += 1
            problems.append(f"{part.name}: JSON PARSE FAIL {exc}")
            continue
        for key, value in data.items():
            if not isinstance(value, str) or not value.strip():
                empty += 1
                problems.append(f"{part.name}: empty value for {key[:60]!r}")
                continue
            filled += 1
            if value == key:
                identical.append(key)
            src_ph = sorted(PLACEHOLDER.findall(key))
            dst_ph = sorted(PLACEHOLDER.findall(value))
            if src_ph != dst_ph:
                problems.append(
                    f"{part.name}: placeholder drift {key[:50]!r} -> {value[:50]!r} {src_ph} != {dst_ph}")
            if key.count("\t") != value.count("\t"):
                problems.append(f"{part.name}: tab count {key[:50]!r} -> {value[:50]!r}")
            if sorted(ENTITY.findall(key)) != sorted(ENTITY.findall(value)):
                problems.append(f"{part.name}: entity drift {key[:50]!r} -> {value[:50]!r}")
            if key.count("&&") != value.count("&&"):
                problems.append(f"{part.name}: '&&' count {key[:50]!r} -> {value[:50]!r}")
    summary[lang] = {
        "parts": len(parts),
        "filled": filled,
        "empty": empty,
        "bad_json": bad_json,
        "identical": len(identical),
        "identical_keys": identical,
    }

total_filled = sum(v["filled"] for v in summary.values())
print(f"locales present: {len(summary)}  filled values: {total_filled}")
print(f"{'lang':<5}{'parts':>6}{'filled':>8}{'empty':>7}{'bad':>5}{'same':>6}")
for lang, v in sorted(summary.items()):
    print(f"{lang:<5}{v['parts']:>6}{v['filled']:>8}{v['empty']:>7}{v['bad_json']:>5}{v['identical']:>6}")
print()
print(f"PROBLEMS: {len(problems)}")
for p in problems[:40]:
    print("  ", p)
Path(".saipen/scratch/t1353_partcheck.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")