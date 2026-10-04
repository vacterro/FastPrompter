"""T-1417 — BUNDLE FINAL-TRUTH / PRIVACY CLOSURE.

The T-1416 fail-open layer started one step too late: ``plan_bundle()`` still
called ``build_silo_index()`` unconditionally, so a parser failure killed
planning and the resilient writer never ran. This module pins the whole
never-block contract:

1. Planner never hard-depends on indexing — a broken parser must still yield a
   BundlePlan, and "Pack With Options" must still be able to open.
2. Final Markdown names only members that actually exist in the ZIP.
3. Paths containing spaces redact completely, not just up to the first space.
4. Every share-safe generated textual surface is privacy-clean.
5. Raw internal exception strings never reach the share archive.
6. Capability flags describe the ACTUAL published bundle, not engine potential.
7. Preflight and published fingerprints describe the same logical payload.
"""

import json
import logging
import os
import zipfile

import pytest

from fastprompter.core import silo_bundle as sb
from fastprompter.core import silo_index

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def png_factory(tmp_path):
    def _create(name: str) -> str:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(PNG_BYTES)
        return str(p)

    return _create


def _md_target(path: str) -> str:
    """A Markdown destination that survives find_markdown_refs' escape handling."""
    return path.replace("\\", "/")


def _members(zip_path: str) -> list:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def _read(zip_path: str, member: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member).decode("utf-8")


def _manifest(zip_path: str) -> dict:
    return json.loads(_read(zip_path, "manifest.json"))


def _boom(*_a, **_kw):
    raise RuntimeError("parser exploded at C:\\Users\\Alice\\Private\\x.md")


# ---------------------------------------------------------------------------
# 1. The planner is intent, not structured-projection authority.
# ---------------------------------------------------------------------------


def test_planner_survives_primary_index_exception(tmp_path, monkeypatch):
    """RED (handoff 3): build_silo_index raising must not abort plan_bundle()."""
    monkeypatch.setattr(silo_index, "build_silo_index", _boom)

    plan = sb.plan_bundle(
        text="# Note\n\n- REQ-A: do a thing\n",
        title="Plan survives",
        target_dir=str(tmp_path / "out"),
    )

    assert isinstance(plan, sb.BundlePlan)
    assert plan.text_member and plan.text_body


def test_planner_survives_all_index_machinery_unavailable(tmp_path, monkeypatch):
    """Every structured-index helper raising at once still yields a plan."""
    for name in ("build_silo_index", "build_fallback_index", "validate_index_structure"):
        monkeypatch.setattr(silo_index, name, _boom)

    plan = sb.plan_bundle(
        text="# Note\n\n- REQ-A: do a thing\n\n![](shot.png)\n",
        title="All indexers dead",
        target_dir=str(tmp_path / "out"),
    )

    assert isinstance(plan, sb.BundlePlan)
    assert plan.text_member and plan.text_body
    assert plan.index_member == "silo.index.json"  # intent survives


def test_options_dialog_admission_does_not_require_an_index(tmp_path, png_factory):
    """No parser/index work may be required merely to display file choices."""
    png_factory("shot.png")
    shot = _md_target(png_factory("shot.png"))

    plan = sb.plan_bundle(
        text=f"# Note\n\n- REQ-A: do a thing\n\n![]({shot})\n",
        title="Dialog admission",
        target_dir=str(tmp_path / "out"),
        silo_dir=str(tmp_path),
    )

    # Everything the dialog needs to render its rows is plan-time intent.
    assert [i.display_name for i in plan.items] == ["shot.png"]
    assert all(i.available for i in plan.items)


def test_write_publishes_when_full_and_fallback_index_both_fail(tmp_path, png_factory, monkeypatch):
    """RED (handoff 3): fail-open holds from the BEGINNING of the pipeline."""
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"# Note\n\n- REQ-A: do a thing\n\n![]({shot})\n",
        title="Both indexers dead",
        target_dir=str(tmp_path / "out"),
    )
    assert isinstance(plan, sb.BundlePlan)

    monkeypatch.setattr(silo_index, "build_silo_index", _boom)
    monkeypatch.setattr(silo_index, "build_fallback_index", _boom)

    result = sb.write_bundle(plan)

    assert result.zip_path and os.path.isfile(result.zip_path)
    assert result.index_status == "unavailable"
    names = _members(result.zip_path)
    assert "silo.index.json" not in names
    assert plan.text_member in names
    assert "README.txt" in names
    assert "manifest.json" in names


# ---------------------------------------------------------------------------
# 2. Final Markdown must match actual ZIP members.
# ---------------------------------------------------------------------------


def test_late_missing_media_leaves_no_broken_markdown_member_link(tmp_path, png_factory):
    """RED (handoff 7): a source that vanishes between plan and write."""
    a = png_factory("a.png")
    b = png_factory("b.png")

    plan = sb.plan_bundle(
        text=(
            "- REQ-A: Keep A\n"
            f"  ![]({_md_target(a)})\n"
            "- REQ-B: Lose B\n"
            f"  ![]({_md_target(b)})\n"
        ),
        title="Late vanish",
        target_dir=str(tmp_path / "out"),
    )
    # item.source is the CANONICAL path, not the spelling used in the document.
    members = {i.display_name: i.member for i in plan.items}
    assert len(members) == 2
    b_member = members["b.png"]

    os.remove(b)  # the source disappears AFTER the plan is built

    result = sb.write_bundle(plan)
    assert result.zip_path

    names = _members(result.zip_path)

    assert members["a.png"] in names
    assert b_member not in names, "a missing source must not produce a ZIP member"

    md = _read(result.zip_path, plan.text_member)
    assert members["a.png"] in md
    assert b_member not in md, "canonical Markdown must not link a nonexistent member"
    assert "b.png" in md  # named honestly, as an omission marker

    manifest = _manifest(result.zip_path)
    statuses = {e["member"]: e["status"] for e in manifest["items"]}
    assert statuses[b_member] == "missing"

    # Structural history may still record the intent; no layer may contradict.
    index = json.loads(_read(result.zip_path, "silo.index.json"))
    req_b = next(r for r in index["requirements"] if "REQ-B" in r["plain_text"])
    assert req_b["media"] == []
    assert b_member in req_b["missing_media"]
    # No requirement anywhere may claim the nonexistent member as present.
    for req in index["requirements"]:
        assert b_member not in req["media"]
        assert b_member not in req.get("unscoped_media", [])


def test_published_fingerprint_equals_preflight_for_unchanged_bundle(tmp_path, png_factory):
    """RED (handoff 23): smart reuse must not regress once planning stops indexing."""
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="Reuse invariant",
        target_dir=str(tmp_path / "out"),
    )

    hashes, _cache = sb.resolve_plan_hashes(plan, {})
    preflight_fp = sb.compute_content_fingerprint(plan, hashes)

    result = sb.write_bundle(plan)
    assert result.zip_path and result.fingerprint

    assert result.fingerprint == preflight_fp
    manifest = _manifest(result.zip_path)
    assert manifest["content_fingerprint"] == preflight_fp
    assert sb.verify_reuse_candidate(result.zip_path, preflight_fp, result.archive_size)


def test_late_vanishing_media_changes_the_published_fingerprint(tmp_path, png_factory):
    """RED (handoff 24): final truth wins over the pre-disappearance identity."""
    a = png_factory("a.png")
    b = png_factory("b.png")
    text = (
        "- REQ-A: Keep A\n"
        f"  ![]({_md_target(a)})\n"
        "- REQ-B: Lose B\n"
        f"  ![]({_md_target(b)})\n"
    )

    plan = sb.plan_bundle(text=text, title="FP truth", target_dir=str(tmp_path / "out"))
    hashes, _cache = sb.resolve_plan_hashes(plan, {})
    preflight_fp = sb.compute_content_fingerprint(plan, hashes)

    os.remove(b)
    result = sb.write_bundle(plan)

    assert result.fingerprint != preflight_fp


# ---------------------------------------------------------------------------
# 3. Path sanitization: spaces must not survive partial redaction.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, must_not_contain",
    [
        (r"C:\Users\Name\file.txt", ["Users", "Name", "C:\\"]),
        (r"C:\Users\Name\My Documents\secret file.txt",
         ["Users", "Name", "My Documents"]),
        (r"C:/Program Files/Test App/tool.exe",
         ["Program Files", "Test App", r"C:/"]),
        ("file:///C:/Program%20Files/Test%20App/tool.exe",
         ["Program", "Files", "Test", "App"]),
        ("file:///C:/Program Files/Test App/tool.exe",
         ["Program", "Files", "Test App"]),
        (r"<C:\Folder With Spaces\file.txt>", ["Folder With Spaces"]),
        ('"C:\\Folder With Spaces\\file.txt"', ["Folder With Spaces"]),
        (r"\\server\share\file.txt", ["server", "share"]),
        (r"\\server\share folder\private dir\report.pdf",
         ["server", "share folder", "private dir"]),
        (r"C:\Users\Ünïcödé\Mes Documents\secret.txt",
         ["Ünïcödé", "Mes Documents"]),
        ("file://server/share folder/private dir/report.pdf",
         ["server", "share folder", "private dir"]),
    ],
)
def test_absolute_local_paths_redact_completely(raw, must_not_contain):
    """No workstation DIRECTORY TAIL survives a redaction.

    The final basename deliberately survives inside the omission marker: that is
    the T-1416 policy this ticket must not revert (``[local file omitted:
    _WIN10_TWEAKER.exe]``), and a bare name is not a path.
    """
    out, count = sb.sanitize_residual_local_paths(raw)

    assert count >= 1, f"expected a redaction in {raw!r}"
    for leaked in must_not_contain:
        assert leaked not in out, f"{leaked!r} leaked from {raw!r} as {out!r}"
    assert "local path omitted" in out


@pytest.mark.parametrize(
    "safe",
    [
        "C: is the third option",
        "file: metadata",
        "https://example.com/?drive=C:",
        "https://example.com/?path=C:\\fake",
        "relative/path/file.txt",
        "see https://example.com/docs/tweaker?drive=C:/test for details",
    ],
)
def test_sanitizer_preserves_false_positive_safety(safe):
    out, count = sb.sanitize_residual_local_paths(safe)
    assert count == 0, f"{safe!r} was wrongly redacted as {out!r}"
    assert out == safe


def test_markdown_target_with_spaces_is_redacted_as_one_token():
    """The canonical parser knows the target boundary; use it."""
    out, count = sb.sanitize_residual_local_paths(
        r"see [Tool](file:///C:/Program Files/Test App/tool.exe) here"
    )
    assert count >= 1
    for leaked in ("Program", "Files", "Test App"):
        assert leaked not in out, f"{leaked!r} leaked as {out!r}"
    assert "here" in out, "trailing prose must survive"


def test_trailing_prose_after_a_bare_path_is_not_swallowed():
    out, _ = sb.sanitize_residual_local_paths(
        r"open C:\Users\Name\file.txt for details"
    )
    assert "for details" in out
    assert "file.txt" in out  # the honest display name is kept


# ---------------------------------------------------------------------------
# 4. One final share-text privacy boundary.
# ---------------------------------------------------------------------------


def test_readme_user_title_cannot_leak_absolute_path(tmp_path, png_factory):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title=r"C:\Users\Alice\Secret Project",
        target_dir=str(tmp_path / "out"),
    )
    result = sb.write_bundle(plan)

    readme = _read(result.zip_path, "README.txt")
    for leaked in ("Alice", r"C:\Users", r"C:\Users\Alice"):
        assert leaked not in readme, f"{leaked!r} leaked into README as {readme!r}"
    assert "local path omitted" in readme


def test_manifest_metadata_cannot_leak_absolute_path(tmp_path, png_factory):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title=r"C:\Users\Alice\Secret Project",
        category=r"D:\Work\Private Category",
        target_dir=str(tmp_path / "out"),
    )
    result = sb.write_bundle(plan)

    raw = _read(result.zip_path, "manifest.json")
    for leaked in ("Alice", r"C:\Users", r"D:\Work", r"D:\Work\Private"):
        assert leaked not in raw, f"{leaked!r} leaked into manifest as {raw!r}"


def test_exported_markdown_cannot_leak_absolute_path(tmp_path, png_factory):
    shot = _md_target(png_factory("shot.png"))
    exe = "file:///C:/Program%20Files/Test%20App/tool.exe"
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n  [Tool]({exe})\n\n![]({shot})\n",
        title="MD privacy",
        target_dir=str(tmp_path / "out"),
    )
    result = sb.write_bundle(plan)

    md = _read(result.zip_path, plan.text_member)
    for leaked in (r"C:/Program", r"C:\Program", "Test App", "Program Files"):
        assert leaked not in md, f"{leaked!r} leaked into exported Markdown as {md!r}"


# ---------------------------------------------------------------------------
# 5. Warning codes are portable; raw exception strings are not.
# ---------------------------------------------------------------------------


def test_raw_exception_text_cannot_leak_local_paths(tmp_path, png_factory, monkeypatch):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="Exception privacy",
        target_dir=str(tmp_path / "out"),
    )

    monkeypatch.setattr(
        silo_index, "build_silo_index",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("parser failed at C:\\Users\\Alice\\Private\\x.md")),
    )
    monkeypatch.setattr(
        silo_index, "build_fallback_index",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("fallback failed at V:\\Secret\\y.md")),
    )

    result = sb.write_bundle(plan)
    assert result.zip_path, "the archive must still publish"

    raw = _read(result.zip_path, "manifest.json")
    manifest = json.loads(raw)

    codes = {w.get("code") for w in manifest["warnings"]}
    assert {"INDEX_PARSE_ERROR", "FALLBACK_INDEX_ERROR", "INDEX_UNAVAILABLE"} <= codes

    for leaked in ("C:\\Users", "V:\\Secret", "Alice", "Private", "parser exploded"):
        assert leaked not in raw, f"{leaked!r} leaked into manifest warnings"

    assert manifest["index_status"] == "unavailable"


def test_raw_exception_text_is_kept_in_the_local_log_not_the_archive(
        tmp_path, png_factory, monkeypatch, caplog):
    """The privacy rule moves the diagnostic, it does not destroy it.

    Silencing the exception inside the archive is only honest while the raw text
    still reaches the operator somewhere local; otherwise a degraded bundle
    becomes undebuggable.
    """
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="Exception diagnostics",
        target_dir=str(tmp_path / "out"),
    )

    monkeypatch.setattr(
        silo_index, "build_silo_index",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("parser failed at C:\\Users\\Alice\\Private\\x.md")),
    )
    monkeypatch.setattr(
        silo_index, "build_fallback_index",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("fallback failed at V:\\Secret\\y.md")),
    )

    with caplog.at_level(logging.ERROR, logger="fastprompter.core.silo_bundle"):
        result = sb.write_bundle(plan)

    logged = "\n".join(
        r.getMessage() + " " + str(r.exc_info[1]) for r in caplog.records
    )
    assert "C:\\Users\\Alice\\Private\\x.md" in logged
    assert "V:\\Secret\\y.md" in logged
    # ...and none of it reached the archive.
    assert "Alice" not in _read(result.zip_path, "manifest.json")


# ---------------------------------------------------------------------------
# 6. Capabilities are final-output facts, not engine potential.
# ---------------------------------------------------------------------------


def test_unavailable_index_has_factual_capability_flags(tmp_path, png_factory, monkeypatch):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="Capability truth",
        target_dir=str(tmp_path / "out"),
    )
    monkeypatch.setattr(silo_index, "build_silo_index", _boom)
    monkeypatch.setattr(silo_index, "build_fallback_index", _boom)

    result = sb.write_bundle(plan)
    caps = _manifest(result.zip_path)["capabilities"]

    assert result.index_status == "unavailable"
    assert caps["structured_requirements"] is False
    assert caps["reverse_media_links"] is False
    assert caps["media_evidence"] is False

    # Always-factual, independent capabilities stay true.
    assert caps["portable_markdown"] is True
    assert caps["member_hashes"] is True
    assert caps["share_safe_paths"] is True
    # Engine capability, not bundle fact.
    assert caps["degraded_index_fallback"] is True


def test_full_index_keeps_factual_capability_flags_true(tmp_path, png_factory):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="Capability full",
        target_dir=str(tmp_path / "out"),
    )
    result = sb.write_bundle(plan)
    assert result.index_status == "full"
    caps = _manifest(result.zip_path)["capabilities"]
    assert caps["structured_requirements"] is True
    assert caps["media_evidence"] is True


# ---------------------------------------------------------------------------
# 7. README instructions must match actual archive members.
# ---------------------------------------------------------------------------


def test_readme_never_asks_for_an_absent_index(tmp_path, png_factory, monkeypatch):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="README reality",
        target_dir=str(tmp_path / "out"),
    )
    monkeypatch.setattr(silo_index, "build_silo_index", _boom)
    monkeypatch.setattr(silo_index, "build_fallback_index", _boom)

    result = sb.write_bundle(plan)
    names = _members(result.zip_path)
    readme = _read(result.zip_path, "README.txt")

    assert "silo.index.json" not in names
    assert "unavailable" in readme.lower()
    assert "1. Read silo.index.json" not in readme


def test_readme_points_at_an_index_that_exists(tmp_path, png_factory):
    shot = _md_target(png_factory("shot.png"))
    plan = sb.plan_bundle(
        text=f"- REQ-A: do a thing\n\n![]({shot})\n",
        title="README present",
        target_dir=str(tmp_path / "out"),
    )
    result = sb.write_bundle(plan)
    assert result.index_status == "full"
    assert "silo.index.json" in _members(result.zip_path)
    assert "1. Read silo.index.json" in _read(result.zip_path, "README.txt")


# ---------------------------------------------------------------------------
# 8. The whole contract, hostile but valid, in one archive.
# ---------------------------------------------------------------------------


def test_hostile_end_to_end_bundle_is_truthful_and_private(tmp_path, png_factory, monkeypatch):
    keep = png_factory("existing.png")
    vanish = png_factory("vanishing.png")
    exe = "file:///C:/Program%20Files/Tool/tool.exe"

    plan = sb.plan_bundle(
        text=(
            "• Main requirement\n"
            f"  [Tool]({exe})\n"
            f"  ![]({_md_target(keep)})\n"
            f"  ![]({_md_target(vanish)})\n"
        ),
        title=r"C:\Users\Alice\Project Notes",
        target_dir=str(tmp_path / "out"),
    )
    assert isinstance(plan, sb.BundlePlan)

    members = {i.display_name: i.member for i in plan.items}
    os.remove(vanish)

    monkeypatch.setattr(
        silo_index, "build_silo_index",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("parser failed at C:\\Users\\Alice\\Private\\x.md")),
    )
    monkeypatch.setattr(
        silo_index, "build_fallback_index",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("fallback failed at V:\\Secret\\y.md")),
    )

    result = sb.write_bundle(plan)
    assert result.zip_path, "clipboard handoff needs a successful ZIP"

    names = _members(result.zip_path)
    assert members["existing.png"] in names
    assert members["vanishing.png"] not in names

    md = _read(result.zip_path, plan.text_member)
    assert members["vanishing.png"] not in md
    for surface, blob in (
        ("markdown", md),
        ("README", _read(result.zip_path, "README.txt")),
        ("manifest", _read(result.zip_path, "manifest.json")),
    ):
        for leaked in (r"C:\Users", "Alice", r"C:/Program", r"V:\Secret"):
            assert leaked not in blob, f"{leaked!r} leaked into {surface}"

    assert "silo.index.json" not in names
    assert result.index_status == "unavailable"
    caps = _manifest(result.zip_path)["capabilities"]
    assert caps["structured_requirements"] is False
    assert caps["media_evidence"] is False


# ---------------------------------------------------------------------------
# 9. The T-1416 operator fixture must stay green.
# ---------------------------------------------------------------------------


def test_operator_seventeen_screenshot_case_remains_full(tmp_path, png_factory):
    shots = [png_factory(f"screen_{i:02d}.png") for i in range(1, 18)]
    shot_refs = "\n".join(f"![screenshot {i}]({_md_target(p)})"
                          for i, p in enumerate(shots, 1))

    note = (
        "# System Maintenance Silo\n"
        "---\n"
        "- REQ-001: Configure telemetry baseline\n"
        "- REQ-002: Backup existing registry hives\n"
        "---\n"
        "- REQ-003: Apply automated optimizations\n"
        "  Refer to upstream documentation at https://example.com/docs/tweaker?drive=C:/test\n"
        "  Local utility archive: [Optimization Tool](file:///V:/private/tools/_WIN10_TWEAKER.exe)\n"
        "  Several prose paragraphs follow to carry the detached screenshots.\n"
        "  Screenshot caption: the tool in action.\n"
        f"{shot_refs}\n"
    )

    plan = sb.plan_bundle(
        text=note,
        title="System Maintenance Silo",
        target_dir=str(tmp_path / "out"),
    )
    result = sb.write_bundle(plan)

    assert result.zip_path and os.path.isfile(result.zip_path)
    assert len(result.items) == 17
    assert not result.missing
    assert result.index_status == "full"
    assert result.bundle_status == "complete"

    names = _members(result.zip_path)
    assert "silo.index.json" in names
    media = [n for n in names if n.startswith("media/")]
    assert len(media) == 17

    md = _read(result.zip_path, plan.text_member)
    assert "https://example.com/docs/tweaker?drive=C:/test" in md, "remote URL untouched"
    assert "file:///V:" not in md and "V:/private" not in md
    # T-1416 policy: the ABSOLUTE PATH is hidden, the basename survives as an
    # honest display name inside the existing omission representation.
    assert "_WIN10_TWEAKER.exe" in md
    assert "[local file omitted: _WIN10_TWEAKER.exe]" in md

    index = json.loads(_read(result.zip_path, "silo.index.json"))
    evidence = index.get("media_evidence", [])
    assert len(evidence) == 17
    assert all(e.get("association") for e in evidence)
