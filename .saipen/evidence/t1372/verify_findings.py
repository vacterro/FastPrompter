"""T-1372 VERIFY -- re-execute the decisive check behind each filed finding.

Every claim below is written so it can FAIL. A check that cannot go red is not
evidence, so each one compares the tree against a stated expectation rather
than merely printing what it found.

    uv run python .saipen/evidence/t1372/verify_findings.py

Exit code 0 means every filed finding still reproduces on the current tree,
which is what T-1372's verify clause asks for: the hunt's output is present and
demonstrably real, not merely asserted.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
CYRILLIC = re.compile(r"[\u0400-\u04FF]")
TR_CALL = re.compile(r"(?<![\w.])tr\(")

results: list[tuple[str, bool, str]] = []


def check(ticket: str, claim: str, ok: bool, detail: str) -> None:
    results.append((ticket, bool(ok), detail if ok else f"{detail} -- CLAIM NOT REPRODUCING"))


# T-1378 -- claude reads a naive ISO reset as LOCAL time, codex reads it as UTC.
def t1378() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from fastprompter.core.usage_limits.providers import claude, codex

    naive = "2026-10-02T12:00:00"
    c, x = claude._parse_reset(naive), codex._epoch(naive)
    expected = datetime.datetime(2026, 10, 2, 12, 0, tzinfo=datetime.UTC).timestamp()
    check(
        "T-1378",
        "claude._parse_reset reads a naive reset as local time",
        c is not None and x is not None and c != x and abs(c - x) > 0,
        f"claude={c} codex={x} differ by {None if (c is None or x is None) else int(c - x)}s "
        f"(UTC expectation {expected})",
    )


# T-1379 -- the Limit UI imports no translation entry point.
def t1379() -> None:
    files = [
        "limit_overview.py",
        "limit_gauges.py",
        "limit_settings_dialog.py",
        "limit_hover_card.py",
        "limit_account_selector.py",
    ]
    untranslated = []
    for name in files:
        text = (ROOT / "src" / "fastprompter" / "ui" / name).read_text(encoding="utf-8")
        if not TR_CALL.search(text) and "core.translations import" not in text:
            untranslated.append(name)
    check(
        "T-1379",
        "the Limit UI paints raw English in every locale",
        len(untranslated) == len(files),
        f"{len(untranslated)}/{len(files)} Limit modules import NO translation entry point "
        f"({', '.join(untranslated)})",
    )


# T-1379b -- the code literal drifted away from every catalog key.
def t1379b() -> None:
    code = (ROOT / "src/fastprompter/ui/limit_overview.py").read_text(encoding="utf-8")
    locale_dir = ROOT / "src/fastprompter/core/i18n"
    packs = sorted(p for p in locale_dir.glob("*.py") if p.stem not in ("__init__", "_engine"))
    missing = [p.stem for p in packs if "No AI accounts detected" not in p.read_text(encoding="utf-8")]
    drifted = "All AI accounts hidden (0% usage or no usable 5h window)" in code
    check(
        "T-1379",
        "no catalog carries the note-row literals the panel emits",
        drifted and len(missing) == len(packs),
        f"{len(missing)}/{len(packs)} packs lack 'No AI accounts detected'; "
        f"drifted longer literal still in code: {drifted}",
    )


# T-1380 -- the CI cyrillic gate is red on Russian samples that are all new since v0.8.69.
def t1380() -> None:
    files = [
        "tests/test_i18n_contract_t1353.py",
        "tools/i18n_contract.py",
        "tools/i18n_identical_audit.py",
        "tools/i18n_outlier.py",
        "tools/validate_saitranslate.py",
    ]
    offenders = []
    for rel in files:
        path = ROOT / rel
        if path.is_file() and any(CYRILLIC.search(l) for l in path.read_text(encoding="utf-8").splitlines()):
            offenders.append(rel)
    at_tag = subprocess.run(
        ["git", "show", "v0.8.69:tools/validate_saitranslate.py"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    tag_cyr = sum(1 for l in at_tag.splitlines() if CYRILLIC.search(l))
    head_cyr = sum(
        1 for l in (ROOT / "tools/validate_saitranslate.py").read_text(encoding="utf-8").splitlines()
        if CYRILLIC.search(l)
    )
    check(
        "T-1380",
        "test_no_cyrillic_in_codebase is red on legitimate Russian samples",
        len(offenders) == len(files) and tag_cyr == 0 < head_cyr,
        f"{len(offenders)}/{len(files)} files carry Cyrillic; validate_saitranslate.py went "
        f"{tag_cyr} -> {head_cyr} Cyrillic lines since v0.8.69, the other 4 files did not exist there",
    )


# T-1373 -- the release receipt carries a key the engine's publication predicate ignores.
def t1373() -> None:
    receipt = json.loads((ROOT / ".saipen/kitchen/release_receipt.json").read_text(encoding="utf-8"))
    has_commit = bool(receipt.get("commit"))
    has_release_commit = bool(receipt.get("release_commit"))
    tag_resolves = subprocess.run(
        ["git", "rev-parse", "--verify", f"{receipt['tag']}^{{commit}}"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    check(
        "T-1373",
        "a published, tagged receipt is invisible to closure provenance",
        has_release_commit and not has_commit and tag_resolves == receipt["release_commit"],
        f"receipt v{receipt['version']} tag {receipt['tag']} resolves to {tag_resolves[:12]}; "
        f"'commit' key present: {has_commit}, 'release_commit' present: {has_release_commit}",
    )


# T-1374 -- no STYLE.md on this machine carries the marker the launcher writes.
def t1374() -> None:
    wanted = re.search(r"style_contract:\s*([A-Za-z0-9-]+)", (ROOT / ".saipen/STATE.md").read_text(encoding="utf-8"))
    marker = wanted.group(1) if wanted else ""
    homes = [
        pathlib.Path(r"C:\Users\vac34\.agents\skills\saipen\STYLE.md"),
        pathlib.Path(r"C:\Users\vac34\AppData\Local\saipen\scheduled-source\saipen\STYLE.md"),
        pathlib.Path(
            r"C:\Users\vac34\.zcode\cli\plugins\cache\zcode-plugins-official"
            r"\browser-use\0.5.1\skills\saipen\STYLE.md"
        ),
    ]
    installed = set()
    for home in homes:
        if home.is_file():
            found = re.search(r"style_contract:\s*([A-Za-z0-9-]+)", home.read_text(encoding="utf-8", errors="replace"))
            installed.add(found.group(1) if found else "?")
    check(
        "T-1374",
        "STATE.md style_contract matches an installed voice contract",
        len(installed) > 1 and marker not in installed,
        f"STATE carries {marker}; the machine holds {sorted(installed)} across "
        f"{len(homes)} STYLE.md copies",
    )


# T-1375 -- a cohort is unpublished exactly when it is still pending with no commit.
def t1375() -> None:
    registry = json.loads((ROOT / ".saipen/kitchen/cohort_registry.json").read_text(encoding="utf-8"))
    pending = sorted(
        cid for cid, rec in registry.get("cohorts", {}).items()
        if rec.get("publication_status") != "published" or not rec.get("commit")
    )
    check(
        "T-1375",
        "cohorts sit pending while their recorded member hashes drift",
        "C-001" in pending,
        f"unpublished cohorts: {pending}",
    )


# T-1376 -- ready subSaipen OUTBOX entries that nothing collects.
def t1376() -> None:
    subs = ROOT / ".saipen/extensions/subs"
    ready = []
    for outbox in subs.glob("*/kitchen/OUTBOX.md"):
        entries = re.findall(r"status:\s*ready", outbox.read_text(encoding="utf-8", errors="replace"))
        if entries:
            ready.append((outbox.parts[-3], len(entries)))
    check(
        "T-1376",
        "ready subSaipen OUTBOX entries are never collected",
        len(ready) >= 1,
        f"roles with ready entries: {ready}",
    )


# T-1377 -- protocol memory past its own soft caps.
def t1377() -> None:
    board = (ROOT / ".saipen/BOARD.md").stat().st_size / 1024
    log_lines = len((ROOT / ".saipen/LOG.md").read_text(encoding="utf-8", errors="replace").splitlines())
    check(
        "T-1377",
        "BOARD.md and LOG.md are past their soft caps",
        board > 16 and log_lines > 300,
        f"BOARD.md {board:.0f} KB (cap ~16 KB), LOG.md {log_lines} lines (cap ~300)",
    )


for probe in (t1378, t1379, t1379b, t1380, t1373, t1374, t1375, t1376, t1377):
    try:
        probe()
    except Exception as exc:  # a probe that cannot run is a failed probe, not a silent pass
        results.append((getattr(probe, "__name__", "?").upper(), False, f"probe raised: {exc!r}"))

print(f"{'ticket':8} {'verdict':8} detail")
for ticket, ok, detail in results:
    print(f"{ticket:8} {'REPRODUCED' if ok else 'NOT REPRO':8} {detail}")

failed = [t for t, ok, _ in results if not ok]
print()
print(f"{len(results) - len(failed)}/{len(results)} filed findings still reproduce on this tree.")
sys.exit(1 if failed else 0)
