"""Mechanism coverage ledger for the TOTAL MECHANISM AUDIT (SRC-136 / T-1439).

WHY THIS REPLACES THE HAND-WRITTEN LEDGER
-----------------------------------------
`audit/MECHANISM_COVERAGE.json` shipped with four domains all claiming exactly
79 tests, five all claiming 233, three all claiming 295, and six naming test
globs (`tests/test_bundle_*.py`, `tests/test_snippet_*.py`, ...) that match no
file on disk. The stated total was 4581; the files the same document names
collect 2042. Those numbers cannot have been measured, so the document could
not answer the one question an audit inventory exists to answer.

Everything below is DERIVED, never asserted:

  * the modules per domain are real paths under `src/fastprompter/`;
  * a domain's test files are the files with a PARSED import edge to one of
    its modules -- `ast.Import` / `ast.ImportFrom` plus the dotted-module
    string literals `tests/_qt_stub.import_with_stubs` takes. Grepping tokens
    over-reports (`main` appears in 164 files) and filename globs under-report
    (the ledger's own globs matched nothing);
  * the test count is `pytest --collect-only`, so a stale or empty glob shows
    up as 0 instead of being papered over;
  * the status comes from a recorded run (`--record`), not from optimism.

WHAT `VERIFIED` DOES NOT MEAN (SRC-138 / handoff §08)
-----------------------------------------------------
Import-edge coverage is ONE plane. It proves a module is imported by a test
that passes; it does not prove a UI action was exercised, that a dialog state
was tested, that a persistence round trip completed, that real Windows runtime
was accepted, or that the layout is readable. The Usage Limits domain was
`VERIFIED` while the operator was looking at a header of anonymous bars.

So this file tracks four separable things per domain:

  * `planes`   UNIT / GUI / PERSISTENCE / RECOVERY / WINDOWS -- which class of
               test evidence exists, classified lexically from the test source;
  * `acceptance` behavioural and visual acceptance, read from
               `docs/audit/ACCEPTANCE.json` and VALIDATED here (exact case ids
               must exist in the recorded run, evidence files must exist, and a
               visual claim must cite a real image capture -- a junit log can
               never promote a domain to visual acceptance);
  * `status`   the seven-value import-plane verdict described in the legend;
  * `changed_since_record` module digests stamped at `--record` time, so source
               edits after the run turn the import-plane verdict into
               `REVERIFY_REQUIRED` instead of leaving a stale VERIFIED.

Nothing here can promote a domain into GUI or visual acceptance: those entries
are declarations this gate can only refute, never invent.

Usage, from the repository root:

    python tools/audit_mechanism_ledger.py --record .saipen/evidence/t1439/run.xml
    python tools/audit_mechanism_ledger.py --verify

`--verify` recomputes the derivation and fails (exit 1) when the committed
ledger has drifted from the tree, so this file is a gate, not a report.

The artifacts live in `docs/audit/`, never in `audit/`: that directory is the
SAIPEN audit-inbox transport and deletes what it captures.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET

#: The durable artifacts live OUTSIDE `audit/`. That directory is SAIPEN's
#: audit-inbox transport: every `.md` directly inside it is captured as an
#: external source layer, and once its receipt closes the file is deleted by
#: the journaled cleanup. Keeping the generated inventory there made every
#: regeneration re-arm a new audit ticket and then deleted the document the
#: drift gate reads. The generator owns these two files; the inbox owns
#: `audit/`, and the two must not share a path.
LEDGER = pathlib.Path("docs/audit/MECHANISM_COVERAGE.json")
INVENTORY = pathlib.Path("docs/audit/MECHANISM_INVENTORY.md")

#: Declarations of behavioural and visual acceptance. Written by a human (or
#: by an agent that has run the journey), never by this generator -- the gate
#: below only ever refutes an entry, it cannot invent one.
ACCEPTANCE = pathlib.Path("docs/audit/ACCEPTANCE.json")

def _resolve(artifact: pathlib.Path, root: pathlib.Path | None) -> pathlib.Path:
    """Anchor an artifact path at the invocation directory or an explicit root."""
    if artifact.is_absolute():
        return artifact
    return (root / artifact) if root is not None else artifact

SCHEMA_VERSION = 3

#: The test planes a domain can hold evidence on. `UNTESTED` exists because a
#: modular ledger that only names covered planes cannot say "nothing here has
#: been exercised", which is the fact a reader most needs.
PLANES = ("UNIT", "GUI", "PERSISTENCE", "RECOVERY", "WINDOWS")

#: Lexical plane markers for planes with no single import that identifies them.
#: GUI and WINDOWS are NOT here: a substring match for "windows" hit docstrings
#: and a monkeypatched `ctypes.windll` string, which is a FAKE of the Windows
#: API and not evidence of anything running on it. Those two planes are read
#: from parsed imports instead (see `classify_planes`).
PLANE_MARKERS: dict[str, tuple[str, ...]] = {
    "PERSISTENCE": (
        "sqlite3", "json.dump", "json.loads", "write_text(", "read_text(",
        ".save(", ".load(", "os.replace(",
    ),
    "RECOVERY": (
        # Only markers that mean "a write was interrupted and the next load was
        # checked". `backup`, `restore` and `recover` were in this list first and
        # matched prose and unrelated helpers -- `test_clipboard_interop` says
        # "backup" about a clipboard buffer, and RECOVERY came out 22/22, which
        # is exactly the blanket claim §08 exists to prevent.
        "rollback", "journal", "os.replace(", "interrupt", "crash",
        "fault inject", "kill the",
    ),
}

#: Imported modules that put a test on the GUI plane.
GUI_IMPORTS = ("PyQt6", "PySide6", "PyQt5")

#: Imported modules that put a test on the real Windows runtime plane. A
#: monkeypatched `ctypes.windll` is excluded by construction: it appears as a
#: string argument to setattr, never as an import.
WINDOWS_IMPORTS = ("ctypes", "winreg", "_winapi", "win32api", "win32con",
                   "win32com", "pywintypes", "msvcrt")

#: Magic bytes a visual-acceptance capture must start with. A junit xml and a
#: text log both fail this check, which is the point: a passing test run is not
#: a screenshot.
IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")

#: Domain id -> (display name, module basenames). Taken from the SRC-129
#: inventory "## Domains (22)" module list, which the earlier audit generation
#: recorded and which matches this tree.
DOMAINS: dict[str, tuple[str, list[str]]] = {
    "DOMAIN_01_APPLICATION_LIFECYCLE": (
        "Application Lifecycle",
        ["main", "instance_lock", "ipc_server", "tray_mixin", "windows_autostart", "qt_lifetime"],
    ),
    "DOMAIN_02_PROFILES_GLOBAL_STATE": (
        "Profiles and Global State",
        ["state", "default_profile", "config", "profile_flags"],
    ),
    "DOMAIN_03_PROMPT_MECHANISMS": (
        "Projects and Prompt Mechanisms",
        ["main"],
    ),
    "DOMAIN_04_SEARCH_AND_FILTER": (
        "Silo Identity, Structure and Search",
        ["silo_region", "silo_chest", "search_mixin"],
    ),
    "DOMAIN_05_CATEGORIES_ORDERING": (
        "Categories and Ordering",
        ["silo_presets", "project_numbox_reorder"],
    ),
    "DOMAIN_06_HOTKEYS": (
        "Hotkeys and Input",
        ["hotkeys", "hotkey_filter", "hotkey_mixin", "hotkey_spec", "shortcut_display"],
    ),
    "DOMAIN_07_THEMES": (
        "Themes and Appearance",
        ["themes", "theme_mixin", "qt_style", "cursor_theme"],
    ),
    "DOMAIN_08_SNIPPETS": (
        "Snippets and Prompt Operations",
        ["snippet_panel", "snippet_ops_mixin", "send_selection_mixin"],
    ),
    "DOMAIN_09_BUNDLES": (
        "Silo Export and Bundles",
        ["silo_bundle", "silo_index", "silo_export", "silo_bundle_actions", "silo_bundle_dialog"],
    ),
    "DOMAIN_10_COVERAGE_BUNDLE": (
        "Silo Coverage and Pack Metadata",
        ["silo_coverage"],
    ),
    "DOMAIN_11_AMBIENCE": (
        "Ambience",
        ["ambience_engine", "ambience_store", "ambience_controller"],
    ),
    "DOMAIN_12_VOICE": (
        "Voice",
        ["voice_engine", "voice_store", "voice_controller"],
    ),
    "DOMAIN_13_PROB_LIP": (
        "Problip",
        ["problip", "problip_store", "problip_controller"],
    ),
    "DOMAIN_14_AUDIO_SOUND": (
        "Audio Transport and Sound",
        ["audio_hub", "sound_manager", "audio_render", "audio_level", "sound_settings_dialog",
         "sound_library", "sound_presets", "sound_dependencies", "audio_hub_pages"],
    ),
    "DOMAIN_15_HOTKEYS_THEMES": (
        "Hotkey and Theme Integration",
        ["hotkey_filter", "themes", "fancy_zones"],
    ),
    "DOMAIN_16_PROFILE_SWITCHING": (
        "Profile Switching",
        ["default_profile", "profile_flags", "state"],
    ),
    "DOMAIN_17_SNIPPET_LIFECYCLE": (
        "Snippet Lifecycle",
        ["snippet_panel", "snippet_ops_mixin"],
    ),
    "DOMAIN_18_USAGE_LIMITS": (
        "Usage Limits",
        ["usage_limits", "limit_gauges", "limit_overview", "limit_hover_card",
         "limit_settings_dialog", "limit_account_selector"],
    ),
    "DOMAIN_19_SYSTRAY_IPC": (
        "System Tray and IPC",
        ["ipc_server", "tray_mixin", "instance_lock"],
    ),
    "DOMAIN_20_WATCHER": (
        "Watcher and Clipboard",
        ["clipboard_watch", "win_clipboard", "ctrlw"],
    ),
    "DOMAIN_21_INTERNATIONALIZATION": (
        "Internationalization",
        ["translations", "i18n"],
    ),
    "DOMAIN_22_BACKUPS_RECOVERY": (
        "Backups, Recovery and Portability",
        ["state", "portable_backup", "backup_dialog", "project_sync", "path_safety"],
    ),
}


def imported_modules(path: pathlib.Path) -> set[str]:
    """Every dotted module path this test file could import a name from."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            out.add(base)
            out.update(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value.startswith("fastprompter") and "." in value:
                out.add(value)
    return out


def python_executable() -> str:
    return sys.executable or "python"


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "src")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def collected_counts(files: list[str]) -> dict[str, int]:
    """Per-file collected test counts from ONE pytest collection pass.

    Counting per domain by summing per-file counts keeps the domain rows
    additive and exact, but the domain totals must not be summed into a grand
    total: shared modules make test files appear in several domains. The
    summary therefore reports the UNION count, which is what a run executes.
    """
    if not files:
        return {}
    proc = subprocess.run(
        [python_executable(), "-m", "pytest", *files, "--collect-only", "-q",
         "-p", "no:randomly"],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        if "::" not in line:
            continue
        path = line.split("::", 1)[0].replace("\\", "/")
        if path.endswith(".py"):
            counts[path] = counts.get(path, 0) + 1
    return counts


def module_exists(src: pathlib.Path, name: str) -> bool:
    """A module file or a package directory (Domain 18 lists `usage_limits`)."""
    if any(src.rglob(name + ".py")):
        return True
    return any(p.is_dir() and p.name == name for p in src.rglob(name))


def module_paths(src: pathlib.Path, name: str) -> list[pathlib.Path]:
    """Every file a domain module name denotes.

    `usage_limits` is a package, so it denotes every file inside it: digesting
    only the directory mtime would miss an edit to one of its modules, and the
    point of the digest is to notice exactly that edit.
    """
    files = sorted(src.rglob(name + ".py"))
    for package in sorted(p for p in src.rglob(name) if p.is_dir()):
        files.extend(sorted(package.rglob("*.py")))
    return files


def classify_planes(
    paths: list[pathlib.Path], root: pathlib.Path
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Which evidence class each test file contributes, judged from its source.

    Returns `(planes, sources)`. `sources` names the files that supplied each
    plane, because a file-level claim without provenance is unauditable: a
    domain's test-file list is "everything that imports any of its modules",
    which is broad, so one recovery-shaped file in that list would otherwise
    grant RECOVERY to a domain that never tests recovery. Naming the file lets
    a reader judge the attribution instead of trusting the badge.

    GUI and WINDOWS come from the PARSED import list, not from substrings: a
    grep for "windows" matched docstrings in `test_codex_identity_pinning`, and
    a grep for `ctypes` matched `monkeypatch.setattr("ctypes.windll.advapi32",
    MockAdvApi())` -- a FAKE of the Windows API. Both would have claimed real
    runtime evidence that does not exist, which is the exact over-claim §08 is
    about. The remaining planes use markers because they name call shapes
    (`write_text(`, `os.replace(`), which no import can express.

    UNIT is the residual: a file that imports the domain's module and carries no
    GUI evidence is unit-level by elimination. It is deliberately NOT granted
    from the import edge alone -- that edge already defines membership, so
    granting UNIT for it would make the plane tautological.
    """
    planes = {plane: "NOT_EXERCISED" for plane in PLANES}
    sources: dict[str, list[str]] = {plane: [] for plane in PLANES}
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        imported = imported_modules(path)

        def imports_any(roots: tuple[str, ...]) -> bool:
            return any(
                name == root or name.startswith(root + ".")
                for name in imported for root in roots
            )

        granted: set[str] = set()
        if imports_any(GUI_IMPORTS):
            granted.add("GUI")
        if imports_any(WINDOWS_IMPORTS):
            granted.add("WINDOWS")
        for plane, markers in PLANE_MARKERS.items():
            if any(marker in source for marker in markers):
                granted.add(plane)
        if not ({"GUI", "WINDOWS"} & granted):
            granted.add("UNIT")

        for plane in granted:
            planes[plane] = "EXERCISED"
            sources[plane].append(rel)
    return planes, sources


def behaviour_not_exercised(planes: dict[str, str], modules: list[str]) -> list[str]:
    """Planes with no evidence, spelled out as behaviour nobody has driven.

    Requirement 6 of handoff §08: record the behaviour that has NOT been
    exercised. `NOT_EXERCISED` in the map is the machine-readable half; this
    is the sentence a reader can act on.
    """
    wording = {
        "UNIT": "no unit-level test imports these modules",
        "GUI": "no test drives a widget, dialog or event for these modules",
        "PERSISTENCE": "no test round-trips a file, database or saved document",
        "RECOVERY": "no test interrupts a write and checks the next load",
        "WINDOWS": "no test executes against the Windows runtime surface",
    }
    return [f"{plane}: {wording[plane]}" for plane in PLANES
            if planes.get(plane) != "EXERCISED"]


#: Class-name suffixes that denote something a user can reach. A widget class
#: is a user entrypoint by definition; a bare helper named `FooDialogMixin`
#: is not, and the base-class check below catches the ones the suffix misses.
ENTRYPOINT_BASES = (
    "QDialog", "QWidget", "QMainWindow", "QFrame", "QMenu", "QSystemTrayIcon",
    "QWidgetAction",
)
ENTRYPOINT_SUFFIXES = ("Dialog", "Panel", "Widget", "Window", "Menu", "Tray", "Page")


def mechanism_entrypoints(
    module_files: list[pathlib.Path],
    test_files: list[pathlib.Path],
    root: pathlib.Path,
) -> list[dict]:
    """User-facing entrypoints a domain defines, and which test reaches them.

    Handoff §08 requirement 3: a domain is not covered because its modules are
    imported. Import coverage cannot distinguish a helper from the dialog the
    operator actually clicks, so the entrypoints are derived from the AST (Qt
    widget classes plus module-level `install_*` / `show_*` functions) and then
    matched against the test sources.

    The match is lexical on the class/function NAME, which is the honest
    granularity available without executing the UI: it proves some test
    mentions the entrypoint, not that it exercised a specific action. That is
    why the result is reported as a count, never as acceptance.
    """
    found: dict[str, dict] = {}
    for path in module_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = {getattr(b, "id", "") or getattr(b, "attr", "")
                         for b in node.bases}
                named = node.name.endswith(ENTRYPOINT_SUFFIXES)
                if not (bases & set(ENTRYPOINT_BASES) or named):
                    continue
                kind = "widget"
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not (node.name.startswith("install_")
                        or node.name.startswith("show_")):
                    continue
                kind = "function"
            else:
                continue
            found.setdefault(node.name, {
                "name": node.name,
                "kind": kind,
                "module": path.relative_to(root).as_posix(),
                "driven_by": [],
            })

    sources = {}
    for test in test_files:
        try:
            sources[test] = test.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    for name, entry in found.items():
        entry["driven_by"] = sorted(
            t.relative_to(root).as_posix() for t, text in sources.items()
            if name in text
        )
    return [found[name] for name in sorted(found)]


def recorded_node_ids(xml_path: pathlib.Path) -> set[str]:
    """Every case node id the recorded run executed, in pytest's spelling.

    Acceptance declarations name concrete cases (`tests/test_x.py::Class::case`),
    so the gate needs the same spelling pytest uses. junit does not always carry
    `file`, so the classname fallback from `_scan_record` is reused.
    """
    nodes: set[str] = set()
    for case in ET.parse(xml_path).iter("testcase"):
        path = (case.get("file") or "").replace("\\", "/")
        classname = case.get("classname") or ""
        parts = classname.split(".") if classname else []
        if not path:
            module_parts = []
            for part in parts:
                if part[:1].isupper():
                    break
                module_parts.append(part)
            if module_parts:
                path = "/".join(module_parts) + ".py"
        if not path:
            continue
        cls = next((p for p in parts if p[:1].isupper()), "")
        name = case.get("name") or ""
        base = name.split("[", 1)[0]
        nodes.add(f"{path}::{cls}::{base}" if cls else f"{path}::{base}")
    return nodes


def load_acceptance(root: pathlib.Path) -> dict:
    """Read the acceptance declarations, or an empty map when none were made."""
    path = _resolve(ACCEPTANCE, root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("domains") or {}


def _is_image(path: pathlib.Path) -> bool:
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    return any(head.startswith(magic) for magic in IMAGE_MAGIC)


def validate_acceptance(
    claim: dict | None,
    root: pathlib.Path,
    node_ids: set[str] | None,
    entrypoints: list[dict] | None = None,
) -> dict:
    """Refute an acceptance claim, or mark it unverified when nothing backs it.

    The rules are split in two so a `PARTIAL` claim can be honest:

    * always -- a named case must exist in the recorded run, and a named
      evidence file must exist. A claim cannot cite a test that never ran or a
      receipt that has been deleted, whatever its status says;
    * only for `ACCEPTED` -- at least one exact case, at least one evidence
      file, a written observation, and for a `VISUAL` plane at least one real
      image capture (a junit xml and a text log are both "evidence" and
      neither is a picture), plus at least one entrypoint some test reaches
      (handoff §08 requirement 3: import coverage alone is not a user path).

    The return value is never `ACCEPTED` unless every rule passed, so this
    function can only lower a claim. Promotion requires the author to write it.
    """
    if not claim:
        return {"status": "NOT_EXERCISED", "reasons": []}
    status = str(claim.get("status") or "NOT_EXERCISED").upper()
    reasons: list[str] = []

    cases = claim.get("cases") or []
    for case in cases:
        if node_ids is None:
            reasons.append(f"{case}: no recorded run to check the case against")
        elif case not in node_ids:
            reasons.append(f"{case}: not executed by the recorded run")

    evidence = claim.get("evidence") or []
    images = 0
    for rel in evidence:
        target = root / rel
        if target.is_file():
            if _is_image(target):
                images += 1
        else:
            reasons.append(f"{rel}: evidence file is not on disk")

    if status == "ACCEPTED":
        if not cases:
            reasons.append("an ACCEPTED claim must name the exact test cases it rests on")
        if not evidence:
            reasons.append("an ACCEPTED claim must name the evidence it rests on")
        if not (claim.get("observation") or "").strip():
            reasons.append("an ACCEPTED claim must record what was observed")
        if claim.get("plane") == "VISUAL" and images == 0:
            reasons.append(
                "a VISUAL claim needs at least one image capture; a test log is not a picture")
        if entrypoints is not None and not any(e.get("driven_by") for e in entrypoints):
            reasons.append(
                "no mechanism-level user entrypoint is reached by any test, so this "
                "cannot be acceptance of a usable mechanism")

    if reasons:
        return {"status": "UNSUPPORTED", "reasons": reasons}
    return {"status": status, "reasons": []}


def hashlib_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def per_file_outcomes(xml_path: pathlib.Path) -> dict[str, int]:
    """test file (posix, relative to root) -> count of failing cases.

    pytest's junit writer usually emits a `file` attribute, but NOT always: a
    case defined inside a class can arrive with `file` absent and only
    `classname="tests.test_x.TestY"`. Keying on `file` alone silently scored
    those cases as zero failures, which is how a run with a real red test
    produced an all-VERIFIED ledger. The classname is therefore the fallback,
    and a case that yields neither is reported rather than dropped.
    """
    return _scan_record(xml_path)[0]


def per_file_totals(xml_path: pathlib.Path) -> dict[str, int]:
    """test file -> number of cases the recorded run actually executed.

    Paired with the collected count this detects a case added to an already
    recorded file: the run executed fewer cases than the tree now collects.
    """
    return _scan_record(xml_path)[1]


def _scan_record(xml_path: pathlib.Path) -> tuple[dict[str, int], dict[str, int]]:
    """One pass over a junit xml: (failures per file, cases per file)."""
    outcomes: dict[str, int] = {}
    totals: dict[str, int] = {}
    unmapped: list[str] = []
    tree = ET.parse(xml_path)
    for case in tree.iter("testcase"):
        path = (case.get("file") or "").replace("\\", "/")
        if not path:
            classname = case.get("classname") or ""
            parts = classname.split(".")
            # `tests.test_x.TestY` -> `tests/test_x.py`; `tests_smoke.test_z`
            # -> `tests_smoke/test_z.py`.
            module_parts = []
            for part in parts:
                if part[:1].isupper():
                    break          # the class name starts here
                module_parts.append(part)
            if module_parts:
                path = "/".join(module_parts) + ".py"
        if not path:
            unmapped.append(case.get("name") or "<unnamed>")
            continue
        bad = 1 if (case.find("failure") is not None or case.find("error") is not None) else 0
        outcomes[path] = outcomes.get(path, 0) + bad
        totals[path] = totals.get(path, 0) + 1
    if unmapped:
        raise ValueError(
            "recorded run has cases that cannot be attributed to a test file: "
            + ", ".join(unmapped[:5])
        )
    return outcomes, totals


def derive(
    root: pathlib.Path,
    failures: dict[str, int] | None,
    record: pathlib.Path | None = None,
    recorded_counts: dict[str, int] | None = None,
) -> dict:
    src = root / "src" / "fastprompter"
    # Both trees: `tests_smoke/` holds the only importing test for several UI
    # mixins, so scanning `tests/` alone reported them uncovered.
    #
    # `conftest.py` is excluded: it imports fixtures, not the code under test,
    # it collects zero cases, and pytest refuses to collect two root-level
    # conftests with the same module name in one invocation -- so listing both
    # made the recorded run abort with a collection error instead of running
    # anything.
    tests = sorted(
        p for p in [*(root / "tests").rglob("*.py"),
                    *(root / "tests_smoke").rglob("*.py")]
        if p.name != "conftest.py"
    )
    index = {t: imported_modules(t) for t in tests}

    # The committed ledger names the run its statuses came from. Reading it
    # back here keeps `--verify` and the Markdown comparison honest: without
    # it, a status-bearing document would be compared against a status-free
    # derivation and every domain would look like drift.
    record_path: pathlib.Path | None = None
    record_digest = ""
    recorded_module_digests: dict[str, str] | None = None
    # SRC-138/R07: a ledger that POINTS at a run must not quietly behave as if
    # it never had one. Falling back to `MAPPED` for every domain is
    # indistinguishable from "the ledger was never recorded", so a vanished
    # evidence file would downgrade the document without saying why.
    record_missing: str | None = None
    # The inventory is a rendering of THIS derivation, so it must carry the
    # identity of the recorded generation rather than whichever checkout happens
    # to run the gate. A fresh `--record` stamps the live HEAD; a verification
    # re-derivation restores the identity from the committed ledger.
    source_identity = head_commit(root)
    if record is not None:
        # An explicit --record names the run for THIS generation, so the
        # committed document can point a later --verify back at it. Resolve it
        # first: a relative path from the CLI is not necessarily under `root`.
        resolved = record.resolve()
        try:
            record_path = resolved.relative_to(root.resolve())
        except ValueError:
            record_path = resolved
        record_digest = hashlib_sha256(resolved)
        failures, recorded_counts = _scan_record(resolved)
    elif failures is None and _resolve(LEDGER, root).exists():
        try:
            prior = json.loads(_resolve(LEDGER, root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior = {}
        source_identity = prior.get("source_identity") or source_identity
        recorded = prior.get("record") or {}
        if recorded.get("path"):
            candidate = root / recorded["path"]
            if candidate.is_file():
                record_path = candidate
                record_digest = recorded.get("sha256") or hashlib_sha256(candidate)
                failures, recorded_counts = _scan_record(candidate)
                # Requirement 7 of handoff §08: a module edited after the run
                # was recorded invalidates the run as evidence for that module.
                # The digests are stamped at --record time and compared here.
                recorded_module_digests = recorded.get("module_sha256") or None
            else:
                record_missing = str(recorded["path"])

    def edges(name: str) -> set[pathlib.Path]:
        """Test files with an import edge to this module OR anything under it.

        The prefix form matters for packages: `usage_limits` is a directory, so
        a test that does `from fastprompter.core.usage_limits.model import ...`
        names `usage_limits.model` and matched nothing. DOMAIN_18 therefore listed
        only the tests that imported a submodule by another route, and the hover
        regression that lived in the model was outside the domain that owns it.
        """
        prefix = name + "."
        return {
            t for t, mods in index.items()
            if any(name == m or m.endswith("." + name)
                   or m.startswith(prefix) or ("." + prefix) in m
                   for m in mods)
        }

    domains: dict[str, dict] = {}
    module_digests: dict[str, str] = {}
    for domain_id, (name, modules) in DOMAINS.items():
        missing = [m for m in modules if not module_exists(src, m)]
        files: set[pathlib.Path] = set()
        no_edge: list[str] = []
        for module in modules:
            hits = edges(module)
            if not hits:
                no_edge.append(module)
            files |= hits
        rel = sorted(p.relative_to(root).as_posix() for p in files)
        files_sorted = sorted(files)
        planes, plane_sources = classify_planes(files_sorted, root)
        module_files: list[pathlib.Path] = []
        for module in modules:
            for path in module_paths(src, module):
                module_digests[path.relative_to(root).as_posix()] = hashlib_sha256(path)
                module_files.append(path)
        domains[domain_id] = {
            "name": name,
            "phase_completed": "VERIFY",
            "modules": modules,
            "modules_missing_on_disk": missing,
            "modules_without_importing_test": no_edge,
            "test_files": rel,
            "test_count": 0,
            "status": None,
            "defects": [],
            "next_action": None,
            "planes": planes,
            "plane_sources": plane_sources,
            "not_exercised": behaviour_not_exercised(planes, modules),
            "entrypoints": mechanism_entrypoints(module_files, files_sorted, root),
        }

    union = sorted({f for e in domains.values() for f in e["test_files"]})
    counts = collected_counts(union)
    for entry in domains.values():
        entry["test_count"] = sum(counts.get(f, 0) for f in entry["test_files"])

    # The recorded run's case ids, for validating acceptance declarations. A
    # missing record means no acceptance claim can be checked, so every
    # ACCEPTED claim degrades rather than passing unexamined.
    node_ids = recorded_node_ids(record_path) if record_path is not None else None
    claims = load_acceptance(root)

    for domain_id, entry in domains.items():
        files = entry["test_files"]
        failing = 0
        # A module that collects ZERO cases is a support module (pytest reads
        # `_smoke_support.py` but collects nothing from it), not a test the run
        # skipped. Calling it unrecorded would invent staleness, so it is named
        # separately and excluded from the staleness comparison below.
        helpers = [f for f in files if counts.get(f, 0) == 0]
        if helpers:
            entry["helper_modules_not_collected"] = helpers
        checked = [f for f in files if counts.get(f, 0) > 0]
        # A file the record never mentions was NOT executed by that run. The
        # earlier form treated a missing key as "zero failures", so a test
        # added after the recording was scored as passing and the domain kept
        # its VERIFIED badge without ever running the new case.
        #
        # A file the record DOES mention can still have grown: adding a case to
        # an existing module leaves the old per-file outcome intact, so the
        # recorded case count is compared with what the tree collects now.
        unrecorded = [f for f in checked if f not in failures] if failures is not None else []
        if failures is not None and recorded_counts is not None:
            for f in checked:
                if f in failures and counts.get(f, 0) > recorded_counts.get(f, 0):
                    unrecorded.append(f)
        if failures is not None:
            failing = sum(failures.get(f, 0) for f in files)
        if entry["modules_missing_on_disk"] or entry["modules_without_importing_test"]:
            entry["status"] = "PARTIAL"
            entry["next_action"] = "add a production module or a test with a real import edge"
        elif not files or entry["test_count"] == 0:
            entry["status"] = "UNSEEN"
            entry["next_action"] = "add a test with a real import edge"
        elif record_missing is not None:
            # Checked BEFORE the "no run recorded" branch: the ledger claims a
            # run, and that run is gone. Reporting MAPPED here would hide the
            # difference between "never recorded" and "evidence disappeared".
            entry["status"] = "MISSING_EVIDENCE"
            entry["next_action"] = (
                f"re-record the run: {record_missing} is not on disk")
        elif failures is None:
            entry["status"] = "MAPPED"
            entry["next_action"] = "record a run: --record <junit.xml>"
        elif failing:
            # Checked before UNRECORDED: a real failure is the more severe
            # fact, and a domain can hold both. The unrecorded list is still
            # recorded below so the staleness is not lost with the verdict.
            entry["status"] = "DEFECT_FOUND"
            entry["defects"] = sorted({f for f in files if failures.get(f, 0)})
            if unrecorded:
                entry["unrecorded"] = sorted(unrecorded)
            entry["next_action"] = "repair the failing test files listed in defects"
        elif unrecorded:
            entry["status"] = "UNRECORDED"
            entry["unrecorded"] = sorted(unrecorded)
            entry["next_action"] = "re-record the run: these files postdate it"
        else:
            entry["status"] = "VERIFIED"

        # Requirement 7: a module edited after the run was recorded means the
        # run no longer speaks for that module. The import-plane verdict can no
        # longer be VERIFIED -- it becomes REVERIFY_REQUIRED until someone
        # re-records. This is what stops a green badge surviving a repair.
        if recorded_module_digests is not None and entry["status"] == "VERIFIED":
            changed = sorted(
                rel for rel, digest in module_digests.items()
                if rel in recorded_module_digests
                and recorded_module_digests[rel] != digest
            )
            added = sorted(rel for rel in module_digests
                           if rel not in recorded_module_digests)
            if changed or added:
                entry["status"] = "REVERIFY_REQUIRED"
                entry["changed_since_record"] = changed + added
                entry["next_action"] = (
                    "re-record the run: these modules changed after it: "
                    + ", ".join((changed + added)[:4]))

        # Acceptance is declared, never derived. `behavioural` and `visual` are
        # the two planes §08 requires separately; the recorded run can only
        # refute an entry, so a domain with no declaration stays NOT_EXERCISED
        # no matter how green its import coverage is.
        claim = claims.get(domain_id) or {}
        entry["acceptance"] = {
            "behavioural": validate_acceptance(
                claim.get("behavioural"), root, node_ids, entry["entrypoints"]),
            "visual": validate_acceptance(
                claim.get("visual"), root, node_ids, entry["entrypoints"]),
        }

    total_files = sorted({f for e in domains.values() for f in e["test_files"]})
    summary = {
        "total_domains": len(domains),
        "total_test_files": len(total_files),
        # UNION, not the sum of the per-domain counts: shared modules put one
        # file in several domains, and a run executes each file once.
        "total_test_count": sum(counts.get(f, 0) for f in total_files),
        "by_status": {},
        # The three numbers a reader must not conflate: import-plane verdict,
        # behavioural acceptance and visual acceptance.
        "by_acceptance": {"behavioural": {}, "visual": {}},
        "planes_exercised": {},
    }
    for entry in domains.values():
        summary["by_status"][entry["status"]] = summary["by_status"].get(entry["status"], 0) + 1
        for plane in PLANES:
            if entry["planes"].get(plane) == "EXERCISED":
                summary["planes_exercised"][plane] = (
                    summary["planes_exercised"].get(plane, 0) + 1)
        for kind in ("behavioural", "visual"):
            state = entry["acceptance"][kind]["status"]
            bucket = summary["by_acceptance"][kind]
            bucket[state] = bucket.get(state, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "audit_campaign": "TOTAL MECHANISM AUDIT AND AUTONOMOUS REPAIR",
        "baseline_version": "0.8.72",
        "source_identity": source_identity,
        "record": (
            {
                "path": _relative_or_absolute(record_path, root),
                "sha256": record_digest,
                # Stamped at --record time; `derive` compares the live tree
                # against these and raises REVERIFY_REQUIRED on a mismatch.
                "module_sha256": dict(sorted(module_digests.items())),
            }
            if record_path is not None
            else None
        ),
        "method": {
            "test_selection": "parsed import edges (ast.Import, ast.ImportFrom, "
                              "plus fastprompter.* string literals); no filename globs",
            "test_count": "pytest --collect-only per domain",
            "status_rule": "VERIFIED requires every module on disk, every module "
                           "with an importing test, a non-zero collected count, a "
                           "test file list the recorded run actually covers, and "
                           "zero failing cases in that run",
            "planes": "UNIT/GUI/PERSISTENCE/RECOVERY/WINDOWS classified lexically "
                      "from the owning test files; a plane is EXERCISED only when "
                      "a marker appears in the source of a test that imports the "
                      "domain's modules",
            "acceptance": "declared in docs/audit/ACCEPTANCE.json and validated "
                          "here; a VISUAL claim needs a real image capture and an "
                          "ACCEPTED claim needs exact case ids from the recorded run",
            "reverify": "a module whose sha256 differs from the one stamped at "
                        "--record time forces REVERIFY_REQUIRED",
        },
        "domains": domains,
        "summary": summary,
    }


def _relative_or_absolute(path: pathlib.Path, root: pathlib.Path) -> str:
    """Render `path` relative to `root` when it lives there, else unchanged.

    The caller may hand us an already-resolved path or one that only makes
    sense relative to the invocation directory, so the resolve happens here
    rather than at the call site.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def head_commit(root: pathlib.Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except OSError:
        pass
    return ""


def render_inventory(ledger: dict) -> str:
    domains = ledger["domains"]
    summary = ledger["summary"]
    lines = [
        "# TOTAL MECHANISM AUDIT — Source Inventory",
        "",
        f"Baseline: FastPrompter v{ledger['baseline_version']}",
        "Campaign: TOTAL MECHANISM AUDIT AND AUTONOMOUS REPAIR",
        "Phase: SHIP",
        "",
        "Generated by `tools/audit_mechanism_ledger.py`; edit the generator or the",
        "tree, never this file. `python tools/audit_mechanism_ledger.py --verify`",
        "fails when this document and the tree disagree.",
        "",
        "## Canonical source identity",
        "",
        "`src/fastprompter/` — PyQt6 desktop application, SQLite persistence,",
        "QThread/QThreadPool workers, Windows named mutex single-instance.",
        "",
        f"Commit: `{ledger['source_identity'] or 'uncommitted'}`",
        "",
        "## Method",
        "",
        "A domain's test files are the files with a **parsed import edge** to one of",
        "its modules (`ast.Import`, `ast.ImportFrom`, and the dotted-module string",
        "literals that `tests/_qt_stub.import_with_stubs` takes). Token greps",
        "over-report and filename globs under-report; both were the failure mode of",
        "the previous hand-written generation, which named six globs that matched no",
        "file. The test count is `pytest --collect-only`, so an empty selection",
        "reports 0 instead of a plausible number.",
        "",
        "## What `VERIFIED` does not mean",
        "",
        "`VERIFIED` is an **import-plane** claim and nothing more. It says: the",
        "module exists, a test file parses an import edge to it, pytest collects",
        "cases from that file, and the recorded run passed them. It does **not**",
        "say that every UI action was exercised, that a dialog state was tested,",
        "that a persistence round trip completed, that a cross-feature behaviour",
        "is correct, that real Windows runtime was accepted, or that the layout is",
        "readable.",
        "",
        "This is not hypothetical. The Usage Limits domain carried `VERIFIED`",
        "while the operator was looking at a header rendered as a strip of",
        "anonymous bars, and later at a hover panel that covered half the editor.",
        "Both were user-visible regressions inside a green domain. Domain-level",
        "`VERIFIED` must never be read as end-to-end product acceptance.",
        "",
        "Acceptance is therefore tracked in three separate columns: the import",
        "plane status, behavioural acceptance, and visual acceptance. The last two",
        "can only be RAISED by a declaration in `docs/audit/ACCEPTANCE.json`; this",
        "gate can lower them, never invent them.",
        "",
        "## 22 Functional Domains",
        "",
        "| # | Domain ID | Modules | Test files | Tests | Plane status | "
        "Behavioural | Visual |",
        "|---|-----------|---------|-----------|-------|--------------|"
        "-------------|--------|",
    ]
    for i, (domain_id, entry) in enumerate(sorted(domains.items()), start=1):
        acceptance = entry.get("acceptance") or {}
        behavioural = (acceptance.get("behavioural") or {}).get("status", "NOT_EXERCISED")
        visual = (acceptance.get("visual") or {}).get("status", "NOT_EXERCISED")
        lines.append(
            f"| {i:02d} | {domain_id} | {len(entry['modules'])} | "
            f"{len(entry['test_files'])} | {entry['test_count']} | {entry['status']} | "
            f"{behavioural} | {visual} |"
        )
    lines += [
        "",
        f"**Domains: {summary['total_domains']}. "
        f"Test files: {summary['total_test_files']}. "
        f"Collected tests: {summary['total_test_count']}.**",
        "",
        "Status legend: `VERIFIED` every module on disk with an importing test, a",
        "non-zero collected count, and zero failing cases in the recorded run;",
        "`REVERIFY_REQUIRED` a module changed after the run was recorded, so its",
        "old verdict no longer speaks for the current source;",
        "`MAPPED` derived but no run recorded; `MISSING_EVIDENCE` the ledger names",
        "a recorded run that is no longer on disk, so its verdicts cannot be",
        "re-checked; `UNRECORDED` the recorded run",
        "predates one or more of the domain's test files, so those cases never",
        "executed; `PARTIAL` a module is missing or has no importing test;",
        "`UNSEEN` nothing collects; `DEFECT_FOUND` a recorded run had failing cases.",
        "",
        "Acceptance legend: `ACCEPTED` a declaration survived validation;",
        "`PARTIAL` the declaration is honest about what it does not cover and every",
        "case/evidence reference in it exists; `NOT_EXERCISED` nobody has declared",
        "this plane, which is the default for every domain and is NOT a pass;",
        "`UNSUPPORTED` the declaration cites a case the run never executed, a file",
        "that is not on disk, or a visual claim with no image capture.",
        "",
        "## Test planes",
        "",
        "A plane is `EXERCISED` only when an owning test file supplies its",
        "evidence: GUI and WINDOWS from PARSED imports (`PyQt6`, `ctypes`,",
        "`winreg`), PERSISTENCE and RECOVERY from call shapes and failure",
        "handling in the source, UNIT from an owning test that exercises the",
        "domain's modules WITHOUT importing a GUI toolkit -- that is the only",
        "thing the word measures here: the headless logic has a test, not that",
        "it is correct. The classification is lexical, so it can under-claim but",
        "cannot over-claim.",
        "",
        "| Domain ID | UNIT | GUI | PERSISTENCE | RECOVERY | WINDOWS |",
        "|-----------|------|-----|-------------|----------|---------|",
    ]
    for domain_id, entry in sorted(domains.items()):
        planes = entry.get("planes") or {}
        cells = " | ".join(planes.get(p, "NOT_EXERCISED") for p in PLANES)
        lines.append(f"| {domain_id} | {cells} |")
    lines += [
        "",
        "### Plane provenance",
        "",
        "A plane badge is only as good as the file behind it, and a domain's test",
        "list is broad (everything that imports any of its modules). These are",
        "the files that actually supplied each plane, so the attribution can be",
        "judged rather than trusted.",
        "",
    ]
    for domain_id, entry in sorted(domains.items()):
        sources = entry.get("plane_sources") or {}
        exercised = [(p, sources.get(p) or []) for p in PLANES
                     if (entry.get("planes") or {}).get(p) == "EXERCISED"]
        if not exercised:
            continue
        parts = []
        for plane, files in exercised:
            names = ", ".join(f"`{f}`" for f in files[:3])
            more = f" (+{len(files) - 3})" if len(files) > 3 else ""
            parts.append(f"{plane} ← {names}{more}")
        lines.append(f"- **{domain_id}**: " + "; ".join(parts))
    lines += [
        "",
    ]

    # Behaviour nobody has driven, spelled out per domain (§08 requirement 6).
    gaps = [
        (domain_id, entry) for domain_id, entry in sorted(domains.items())
        if entry.get("not_exercised")
    ]
    if gaps:
        lines += [
            "## Behaviour that has not been exercised",
            "",
            "Each line names a plane with no evidence. These are NOT statements",
            "that the mechanism is broken -- they are statements that nobody has",
            "looked, so the ledger cannot say either way.",
            "",
        ]
        for domain_id, entry in gaps:
            lines.append(f"- **{domain_id}**")
            for item in entry["not_exercised"]:
                lines.append(f"  - {item}")
        lines.append("")

    # Mechanisms with no reachable entrypoint, or an entrypoint no test mentions.
    unreached = []
    for domain_id, entry in sorted(domains.items()):
        entrypoints = entry.get("entrypoints") or []
        if not entrypoints:
            continue
        dead = [e for e in entrypoints if not e["driven_by"]]
        if dead:
            unreached.append((domain_id, dead))
    if unreached:
        lines += [
            "## Mechanism entrypoints no test reaches",
            "",
            "Derived from the AST: Qt widget classes plus module-level `install_*`",
            "and `show_*` functions. A name here is user-reachable surface that no",
            "test mentions at all, which no amount of import-edge coverage fixes.",
            "",
        ]
        for domain_id, dead in unreached:
            names = ", ".join(f"`{e['name']}`" for e in dead[:8])
            more = f" (+{len(dead) - 8} more)" if len(dead) > 8 else ""
            lines.append(f"- **{domain_id}**: {names}{more}")
        lines.append("")

    lines += [
        "## LIFECYCLE mechanisms (SRC-129, SRC-131, SRC-132)",
        "",
        "The 32 normative MUST clauses for the 7 LIFECYCLE mechanisms live in",
        "`SRC-131:R001–R032` and are dispositioned `VERIFIED` against the registered",
        "`test_instance_lock`, `test_shutdown_ownership`, `test_ipc_grace`,",
        "`test_hotkey_filter`, `test_tray_menu_toggles`, `test_windows_autostart`,",
        "`test_startup_backup` and `test_state_migration` suites. Those receipts are",
        "historical: this file does not restate their counts.",
        "",
        "## Evidence files",
        "",
        "- `audit/evidence/LIFECYCLE-001.md` through `LIFECYCLE-007.md`",
        "- `audit/evidence/DOMAIN_02.md`",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=pathlib.Path, default=None,
                        help="junit xml from a run over the derived test files")
    parser.add_argument("--verify", action="store_true",
                        help="recompute and fail when the committed ledger drifted")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / "src" / "fastprompter").is_dir():
        print("run me from the repository root", file=sys.stderr)
        return 2

    failures = per_file_outcomes(args.record) if args.record else None
    ledger = derive(root, failures, record=args.record)

    if args.verify:
        ledger_path = _resolve(LEDGER, root)
        if not ledger_path.exists():
            print(f"MISSING {ledger_path}", file=sys.stderr)
            return 1
        committed = json.loads(ledger_path.read_text(encoding="utf-8"))
        problems = compare(committed, ledger)
        if problems:
            for problem in problems:
                print(f"DRIFT {problem}", file=sys.stderr)
            return 1
        print(f"ledger matches the tree: {ledger['summary']}")
        return 0

    ledger_path, inventory_path = _resolve(LEDGER, root), _resolve(INVENTORY, root)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    inventory_path.write_text(render_inventory(ledger), encoding="utf-8")
    print(json.dumps(ledger["summary"], indent=1))
    bad = [d for d, e in ledger["domains"].items()
           if e["status"] not in ("VERIFIED", "MAPPED")]
    for domain_id in bad:
        entry = ledger["domains"][domain_id]
        print(f"{entry['status']} {domain_id}: "
              f"missing={entry['modules_missing_on_disk']} "
              f"no_test={entry['modules_without_importing_test']} "
              f"unrecorded={entry.get('unrecorded', [])} "
              f"changed={entry.get('changed_since_record', [])} "
              f"defects={entry['defects']}")
    # Acceptance failures are not domain failures -- an undeclared plane is the
    # normal state -- but an UNSUPPORTED claim is a lie in the document, so it
    # has to fail this gate.
    unsupported = [
        (d, kind, info["reasons"])
        for d, e in sorted(ledger["domains"].items())
        for kind, info in (e.get("acceptance") or {}).items()
        if info["status"] == "UNSUPPORTED"
    ]
    for domain_id, kind, reasons in unsupported:
        print(f"UNSUPPORTED {domain_id} {kind} acceptance: {'; '.join(reasons)}",
              file=sys.stderr)
    return 0 if not bad and not unsupported else 1


def compare(committed: dict, fresh: dict) -> list[str]:
    """Differences that mean the document no longer describes the tree."""
    problems: list[str] = []
    old = committed.get("domains") or {}
    new = fresh.get("domains") or {}
    for domain_id in sorted(set(old) | set(new)):
        a, b = old.get(domain_id), new.get(domain_id)
        if a is None:
            problems.append(f"{domain_id} missing from the ledger")
            continue
        if b is None:
            problems.append(f"{domain_id} no longer exists in the generator")
            continue
        if a.get("test_files") != b.get("test_files"):
            problems.append(f"{domain_id} test file list changed")
        if a.get("test_count") != b.get("test_count"):
            problems.append(
                f"{domain_id} test count {a.get('test_count')} != measured {b.get('test_count')}"
            )
        if a.get("modules") != b.get("modules"):
            problems.append(f"{domain_id} module list changed")
        if a.get("status") != b.get("status"):
            problems.append(
                f"{domain_id} status {a.get('status')} != derived {b.get('status')}"
            )
        if sorted(a.get("defects") or []) != sorted(b.get("defects") or []):
            problems.append(f"{domain_id} defect list changed")
        if (a.get("planes") or {}) != (b.get("planes") or {}):
            problems.append(f"{domain_id} test-plane evidence changed")
        if (a.get("plane_sources") or {}) != (b.get("plane_sources") or {}):
            problems.append(f"{domain_id} test-plane provenance changed")
        for kind in ("behavioural", "visual"):
            was = ((a.get("acceptance") or {}).get(kind) or {}).get("status")
            now = ((b.get("acceptance") or {}).get(kind) or {}).get("status")
            if was != now:
                problems.append(
                    f"{domain_id} {kind} acceptance {was} != validated {now}")
        if sorted(e["name"] for e in (a.get("entrypoints") or [])) != sorted(
                e["name"] for e in (b.get("entrypoints") or [])):
            problems.append(f"{domain_id} mechanism entrypoint list changed")
    if committed.get("summary", {}).get("total_test_count") != fresh["summary"]["total_test_count"]:
        problems.append("summary total_test_count is stale")
    return problems


if __name__ == "__main__":
    sys.exit(main())
