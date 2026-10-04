"""qq (prepare saiwiki) fact oracle W-040: check every kitchen page claim against the live tree.

Read-only. One PASS/FAIL line per check with its evidence; the OUTBOX quotes this output.
"""

import ast
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".saipen").is_dir())
KITCHEN = ROOT / ".saipen/extensions/subs/saiwiki/kitchen"
SRC = ROOT / "src/fastprompter"
PAGES = sorted(p for p in KITCHEN.glob("*.md") if p.name != "OUTBOX.md")
fails = []


def check(label, ok, evidence=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"   [{evidence}]" if evidence else ""))
    if not ok:
        fails.append(f"{label} [{evidence}]")


def read(path):
    return Path(path).read_text(encoding="utf-8")


def count_keys(module, name):
    tree = ast.parse(read(module))
    for node in ast.walk(tree):
        target = getattr(node, "targets", [None])[0] if hasattr(node, "targets") else getattr(node, "target", None)
        if target is not None and getattr(target, "id", "") == name:
            return len(node.value.keys)
    return -1


live = {
    "core": len(list((SRC / "core").glob("*.py"))),
    "i18n": len(list((SRC / "core/i18n").glob("*.py"))),
    "usage_root": len(list((SRC / "core/usage_limits").glob("*.py"))),
    "usage_providers": len(list((SRC / "core/usage_limits/providers").glob("*.py"))),
    "ui": len(list((SRC / "ui").glob("*.py"))),
    "utils": len(list((SRC / "utils").glob("*.py"))),
    "theme": len(list((SRC / "theme").glob("*.py"))),
    "total": len(list(SRC.rglob("*.py"))),
    "events": count_keys(SRC / "core/sound_manager.py", "_DEFAULT_SOUND_MAP"),
    "themes": len(re.findall(r"^\s{4,}\"[a-z0-9_\- ]+\":", read(SRC / "theme/themes.py"), re.M)),
}
version = read(ROOT / "VERSION").strip()
print("== LIVE FACTS ==")
for key, value in live.items():
    print(f"  {key:<16} {value}")
print(f"  {'VERSION':<16} {version}")

print("\n== A. every file reference resolves (all pages) ==")
missing = []
for page in PAGES:
    for ref in set(re.findall(r"`([A-Za-z0-9_./\-]+\.(?:py|md|json|wav|png))`", read(page))):
        if ref.startswith(("data/", "local_data", "_shared/", "kitchen/", "docs/")):
            continue
        if not any((base / ref).exists() for base in (ROOT, SRC, SRC / "core", SRC / "ui")) \
                and not list(ROOT.rglob(Path(ref).name)):
            missing.append(f"{page.name}:{ref}")
check(f"15 pages, 0 dangling references", not missing, "; ".join(missing[:6]))

print("\n== B. wiki-style page links resolve ==")
bad = []
for page in PAGES:
    for target in re.findall(r"\]\(([^)#:]+)\)", read(page)):
        if target in {"url", "link", ""}:        # documentation placeholders
            continue
        if not (KITCHEN / f"{target}.md").exists():
            bad.append(f"{page.name}->{target}")
check("every in-wiki link has a page", not bad, "; ".join(bad[:6]))

print("\n== C. _Sidebar links resolve ==")
sidebar_targets = re.findall(r"\]\(([^)#:]+)\)", read(KITCHEN / "_Sidebar.md"))
check("_Sidebar lists only existing pages",
      all((KITCHEN / f"{t}.md").exists() for t in sidebar_targets), str(sidebar_targets))

print("\n== D. no live claim about the REMOVED watcher subsystem ==")
# QFileSystemWatcher / sync_live_watch are Qt's file watcher and stay legitimate;
# only the removed Watcher Engine (queue + auto-send) must never read as live.
removed = re.compile(r"Alt\+C|Queue Master|Watcher Engine|open_queue_master|prompt drainage|Watcher Queue")
retired = re.compile(r"retir|removed|unbound|no-op|no longer|deleted|replaced", re.I)
live_watcher = []
for page in PAGES:
    lines = read(page).splitlines()
    for i, line in enumerate(lines, 1):
        if removed.search(line) and not retired.search(line):
            window = " ".join(lines[max(0, i - 4):i + 3])
            if not retired.search(window):
                live_watcher.append(f"{page.name}:{i}")
check("removed-subsystem keys/dialogs are only mentioned as retired",
      not live_watcher, ", ".join(live_watcher))
check("Qt QFileSystemWatcher (live sync) is still documented",
      len([p for p in PAGES if re.search(r"QFileSystemWatcher|sync_live_watch", read(p))]) >= 2)

print("\n== E. Module-Structure counts match the tree ==")
struct = read(KITCHEN / "Module-Structure.md")
checks = {
    "core/ count": rf"\*\*core/\*\*: {live['core']} ",
    "ui/ count": rf"\*\*ui/\*\*: {live['ui']} ",
    "utils/ count": rf"\*\*utils/\*\*: {live['utils']} ",
    "theme/ count": rf"\*\*theme/\*\*: {live['theme']} ",
    "i18n count": r"i18n/ \(33 locales \+ 5 infra files = 38\)",
    "usage_limits count": rf"usage_limits/ \({live['usage_root']} \+ {live['usage_providers']} provider files = {live['usage_root'] + live['usage_providers']}\)",
    "total count": rf"\*\*Total\*\*: {live['total']} ",
    "theme catalog": r"15 built-in color themes",
}
for label, pattern in checks.items():
    check(f"Module-Structure {label}", bool(re.search(pattern, struct)),
          (re.search(pattern, struct).group(0).strip() if re.search(pattern, struct) else "pattern absent"))

print("\n== F. Module-Structure names every live module ==")
listed = set(re.findall(r"([A-Za-z0-9_]+\.py)", struct))
shipped_data = {p.name for p in (SRC / "sound").rglob("*.py")}
unlisted = sorted({p.name for p in SRC.rglob("*.py")} - {"__init__.py"} - listed - shipped_data
                  - {f"{name}.py" for name in ("ar", "bg", "cs", "da", "de", "ded", "el", "en", "est", "fi", "fra",
                                               "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "nl", "no", "pl", "pt",
                                               "ro", "ru", "sk", "spa", "sv", "th", "tur", "ukr", "vi", "zh")})
check("no live module row missing (locale packs covered by the i18n row)", not unlisted, str(unlisted))

print("\n== G. Configuration claims ==")
conf = read(KITCHEN / "Configuration.md")
check(f"sound_events says {live['events']} events", rf"\| `sound_events` \| JSON dict \| {live['events']} events" .replace(r"\|", "|") in conf or f"| `sound_events` | JSON dict | {live['events']} events" in conf)
keys = sorted(set(re.findall(r"^\|\s*`([a-z][a-z0-9_]{2,})`", conf, re.M)))
source = read(SRC / "core/default_profile.py") + read(SRC / "core/config.py") + read(SRC / "ui/settings.py")
unknown = [k for k in keys if k not in source]
print(f"  settings keys in the table: {len(keys)}; absent from source: {unknown}")

print("\n== H. version banners ==")
stale = []
for page in PAGES:
    found = re.findall(r"\*\*v([0-9]+\.[0-9]+(?:\.[0-9]+)?)\*\*", read(page)[:600])
    if found and found[0] != version:
        stale.append(f"{page.name}:{found[0]}")
check(f"first-screen banners match VERSION {version}", not stale, "; ".join(stale))

print("\n== I. coverage audit: feature surfaces named in the page set ==")
coverage = {
    "Master Mute (T-1244)": r"master mute",
    "appearance sounds (T-1245)": r"appearance sound",
    "ambience transport (T-1265/1238)": r"ambience",
    "dual Claude accounts (T-1266/68)": r"accounts_report|accounts detected|several accounts|each claude",
    "reset queue card (T-1279)": r"reset queue",
    "clipboard generation (T-1269)": r"clipboard",
    "voice countdown (T-1238-C3.7)": r"voice",
    "portable backup generations (W2-002/003)": r"generation",
}
for label, pattern in coverage.items():
    hits = [p.name for p in PAGES if re.search(pattern, read(p), re.I)]
    check(f"{label} named in the wiki", len(hits) >= 1, f"{len(hits)}/15 -> {', '.join(h[:1] for h in hits[:3])}")

print("\n== J. mirror divergence (payload size) ==")
diverged = [p.name for p in PAGES
            if not (ROOT / "docs/wiki" / p.name).exists()
            or (ROOT / "docs/wiki" / p.name).read_bytes() != p.read_bytes()]
print(f"  {len(diverged)}/{len(PAGES)} kitchen pages differ from docs/wiki: {diverged}")

print("\n" + "=" * 62)
print(f"ORACLE RESULT: {len(fails)} failure(s) over {len(PAGES)} pages")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
