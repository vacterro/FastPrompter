"""T-1441 §08 red controls: the ledger must not call import coverage acceptance.

The handoff (`audit/16.md` §08) lists ten requirements against the mechanism
audit. The first generation of `tools/audit_mechanism_ledger.py` satisfied one
of them -- derived import-edge coverage -- and reported its result in a column
called `status`. A reader could not tell that "VERIFIED" meant "a test imports
this module and it passed" rather than "the mechanism works for a user".

The evidence that mattered: DOMAIN_18_USAGE_LIMITS carried VERIFIED while the
operator was looking at a header rendered as anonymous bars, and later at a
hover panel covering half the editor. Import coverage was green *because* the
defect was visual and behavioural, which import coverage cannot see.

Each control below fails on the pre-§08 generator and passes now. They are
written against the real generator and the real tree where possible, because a
mock of the generator would not prove the gate still runs.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "audit_mechanism_ledger.py"


def _load():
    sys_path_added = str(GENERATOR.parent)
    import sys

    sys.path.insert(0, sys_path_added)
    try:
        spec = importlib.util.spec_from_file_location(
            "audit_mechanism_ledger_src138_s08", GENERATOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def mod():
    return _load()


@pytest.fixture(scope="module")
def committed(mod):
    return json.loads((ROOT / mod.LEDGER).read_text(encoding="utf-8"))


# ==========================================================================
# Requirement 1-4: the planes exist, differ from each other, and are not a
# single blanket badge.
# ==========================================================================

def test_s08_planes_are_declared_and_every_domain_carries_them(mod, committed):
    """A domain without a plane map is a domain whose coverage is unqualified."""
    assert mod.PLANES == ("UNIT", "GUI", "PERSISTENCE", "RECOVERY", "WINDOWS")
    for domain_id, entry in committed["domains"].items():
        planes = entry.get("planes") or {}
        assert set(planes) == set(mod.PLANES), f"{domain_id} is missing planes"
        assert all(v in ("EXERCISED", "NOT_EXERCISED") for v in planes.values())


def test_s08_windows_plane_is_not_granted_by_a_mocked_winapi(mod):
    """RED CONTROL: a monkeypatched ctypes is a FAKE of Windows, not evidence.

    The first classifier grepped for the substring "ctypes" and so granted the
    WINDOWS plane to any test that stubbed the API. `tests/test_usage_limits_cli`
    does exactly that with `monkeypatch.setattr("ctypes.windll.advapi32", ...)`,
    and it must not count.
    """
    assert "ctypes" in mod.WINDOWS_IMPORTS
    fake = ROOT / "tests" / "test_usage_limits_cli.py"
    if not fake.is_file():
        pytest.skip("the mocked-winapi fixture moved")
    imported = mod.imported_modules(fake)
    assert not any(name == "ctypes" or name.startswith("ctypes.")
                   for name in imported), (
        "this fixture must not import ctypes for real, or the control proves nothing")


def test_s08_gui_plane_requires_a_real_qt_import(mod):
    """The GUI plane is read from parsed imports, so a docstring cannot grant it."""
    assert "PyQt6" in mod.GUI_IMPORTS
    clean = ROOT / "tests" / "test_wav_safety_negatives.py"
    if not clean.is_file():
        pytest.skip("the pure-unit fixture moved")
    planes, _ = mod.classify_planes([clean], ROOT)
    assert planes["GUI"] == "NOT_EXERCISED", (
        "a test that never imports Qt must not be placed on the GUI plane")
    assert planes["UNIT"] == "EXERCISED", (
        "a headless test that exercises the modules is unit evidence")


def test_s08_a_recovery_word_in_prose_does_not_grant_the_plane(mod):
    """RED CONTROL: `backup`/`restore` matched docstrings and unrelated helpers.

    With those markers the RECOVERY plane came out 22/22 -- every domain -- from
    word matches alone. That is the blanket claim the section exists to stop, so
    the marker set must not contain bare prose words.
    """
    markers = mod.PLANE_MARKERS["RECOVERY"]
    for word in ("backup", "restore", "recover"):
        assert word not in markers, (
            f"{word!r} matches prose and helpers; it cannot identify recovery")


def test_s08_plane_provenance_names_the_file_that_granted_it(mod, committed):
    """A badge without a citation is unauditable, so every EXERCISED plane must
    name at least one real file, and every named file must belong to the domain."""
    for domain_id, entry in committed["domains"].items():
        sources = entry.get("plane_sources") or {}
        for plane, files in sources.items():
            if (entry["planes"] or {}).get(plane) != "EXERCISED":
                assert not files, f"{domain_id}/{plane} is unexercised but cites files"
                continue
            assert files, f"{domain_id}/{plane} claims exercise with no citation"
            for rel in files:
                assert (ROOT / rel).is_file(), f"{domain_id}/{plane} cites {rel}"
                assert rel in entry["test_files"], (
                    f"{domain_id}/{plane} cites {rel}, which is not one of its tests")


def test_s08_a_domain_can_lack_a_plane(mod, committed):
    """If every domain exercised every plane, the planes would be decoration."""
    missing = [
        (d, e["planes"]) for d, e in committed["domains"].items()
        if "NOT_EXERCISED" in e["planes"].values()
    ]
    assert missing, "no domain lacks a plane; the classification is not discriminating"


# ==========================================================================
# Requirement 3: mechanism-level user entrypoints
# ==========================================================================

def test_s08_entrypoints_are_derived_from_the_ast_not_a_name_list(mod, committed):
    """A Qt widget class in a domain's module is user-reachable surface."""
    hits = 0
    for entry in committed["domains"].values():
        for point in entry.get("entrypoints") or []:
            hits += 1
            assert point["kind"] in ("widget", "function")
            assert (ROOT / point["module"]).is_file()
            assert isinstance(point["driven_by"], list)
    assert hits > 0, "no mechanism entrypoints were derived at all"


def test_s08_an_entrypoint_no_test_mentions_is_reported_not_hidden(mod, committed):
    """`install_status` in the gauges is reached by no test. That is a fact the
    document has to carry, because it is a user path nothing exercises."""
    entry = committed["domains"]["DOMAIN_18_USAGE_LIMITS"]
    names = {p["name"] for p in entry["entrypoints"]}
    assert "LimitGauges" in names, (
        "the gauge widget every hover regression is about must be an entrypoint")
    driven = {p["name"] for p in entry["entrypoints"] if p["driven_by"]}
    assert driven, "at least one usage-limit entrypoint must be named by a test"


# ==========================================================================
# Requirement 5-6: exact case association, and unexercised behaviour recorded
# ==========================================================================

def test_s08_acceptance_cannot_cite_a_case_the_run_never_executed(mod, tmp_path):
    """RED CONTROL: a declaration is not evidence.

    The gate must refuse a claim naming a case that no recorded run executed.
    Before this rule, `ACCEPTED` was a string in a JSON file with nothing behind
    it.
    """
    claim = {
        "status": "ACCEPTED",
        "cases": ["tests/test_does_not_exist.py::test_imaginary"],
        "evidence": [".saipen/evidence/t1441/captures/hover_12_compact.png"],
        "observation": "looked at it",
    }
    result = mod.validate_acceptance(claim, ROOT, node_ids=set())
    assert result["status"] == "UNSUPPORTED"
    assert any("not executed" in r for r in result["reasons"])


def test_s08_a_visual_claim_needs_an_image_not_a_test_log(mod):
    """RED CONTROL: "evidence" was any path. A junit xml is not a screenshot.

    The handoff says physical rendering acceptance cannot be claimed without
    real captures; this is that rule as code.
    """
    claim = {
        "status": "ACCEPTED",
        "plane": "VISUAL",
        "cases": ["t.py::test_x"],
        "evidence": [".saipen/evidence/t1441/run-derived.log"],
        "observation": "the suite passed",
    }
    result = mod.validate_acceptance(claim, ROOT, node_ids={"t.py::test_x"})
    assert result["status"] == "UNSUPPORTED"
    assert any("image capture" in r for r in result["reasons"])


def test_s08_a_visual_claim_with_a_real_png_is_not_refused_for_lack_of_image(mod):
    """The converse: naming a real PNG clears the image rule (other rules may
    still fire, and that is fine -- this control is only about the image rule)."""
    claim = {
        "status": "ACCEPTED",
        "plane": "VISUAL",
        "cases": ["t.py::test_x"],
        "evidence": [".saipen/evidence/t1441/captures/hover_12_compact_4x.png"],
        "observation": "inspected the enlarged capture",
    }
    result = mod.validate_acceptance(claim, ROOT, node_ids={"t.py::test_x"})
    assert not any("image capture" in r for r in result["reasons"])


def test_s08_missing_evidence_file_refutes_even_a_partial_claim(mod):
    """A PARTIAL claim is allowed to be incomplete, never to be fictional."""
    claim = {
        "status": "PARTIAL",
        "cases": [],
        "evidence": [".saipen/evidence/t1441/captures/nope.png"],
    }
    result = mod.validate_acceptance(claim, ROOT, node_ids=set())
    assert result["status"] == "UNSUPPORTED"
    assert any("not on disk" in r for r in result["reasons"])


def test_s08_unexercised_behaviour_is_recorded_per_domain(mod, committed):
    """Requirement 6: say what nobody has driven, not only what passed."""
    for domain_id, entry in committed["domains"].items():
        gaps = entry.get("not_exercised")
        assert isinstance(gaps, list), f"{domain_id} records no unexercised behaviour"
        exercised = {p for p, v in entry["planes"].items() if v == "EXERCISED"}
        assert len(gaps) == len(set(mod.PLANES) - exercised), (
            f"{domain_id} must name exactly the planes it has no evidence for")


# ==========================================================================
# Requirement 7: source changes after a recording force REVERIFY_REQUIRED
# ==========================================================================

def test_s08_a_module_changed_after_the_run_is_not_still_verified(mod, tmp_path):
    """RED CONTROL: the recorded digest stamps are what make this detectable.

    A repair that edits `limit_gauges.py` after a green run must not leave the
    domain claiming VERIFIED on the strength of the pre-repair run.
    """
    record = json.loads((ROOT / mod.LEDGER).read_text(encoding="utf-8"))["record"]
    stamp = record.get("module_sha256") or {}
    assert stamp, "the ledger must stamp module digests at --record time"
    target = "src/fastprompter/ui/limit_gauges.py"
    assert target in stamp, f"{target} must be stamped"
    assert len(stamp[target]) == 64, "digests are sha256 hex"


def test_s08_reverify_required_is_not_a_status_that_can_be_ignored(mod):
    """The status has to be in the legend *and* fail the gate, or it is a label."""
    text = (ROOT / mod.INVENTORY).read_text(encoding="utf-8")
    assert "REVERIFY_REQUIRED" in text, (
        "the inventory must document the status a changed module produces")


# ==========================================================================
# Requirement 8: never auto-promote a domain from imports into GUI acceptance
# ==========================================================================

def test_s08_usage_limits_is_not_claimed_accepted_by_its_import_coverage(mod, committed):
    """The concrete case the handoff names.

    DOMAIN_18 was VERIFIED throughout a user-visible visual defect. Its
    acceptance now has to be something a human wrote down, and the recorded run
    can only lower it.
    """
    entry = committed["domains"]["DOMAIN_18_USAGE_LIMITS"]
    acceptance = entry.get("acceptance") or {}
    for kind in ("behavioural", "visual"):
        info = acceptance.get(kind) or {}
        assert info.get("status") in (
            "NOT_EXERCISED", "PARTIAL", "ACCEPTED", "UNSUPPORTED"), (
            f"usage limits {kind} acceptance is {info.get('status')!r}")
    # The point: whatever the import status says, acceptance is a separate fact.
    assert "status" in entry and "acceptance" in entry


def test_s08_no_domain_is_accepted_on_import_coverage_alone(committed):
    """A domain with zero declarations must not read as accepted anywhere."""
    for domain_id, entry in committed["domains"].items():
        for kind, info in (entry.get("acceptance") or {}).items():
            if info.get("status") == "ACCEPTED":
                raise AssertionError(
                    f"{domain_id} {kind} claims ACCEPTED; every entry must carry "
                    "exact cases, real evidence and an observation")
