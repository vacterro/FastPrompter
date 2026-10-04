"""T-1416 — BUNDLE NEVER-BLOCK + EVIDENCE ASSOCIATION HARDENING.

Robustness regressions and architectural invariants:
1. Operator production failure reproduction:
   Markdown note containing normal requirements, prose, https remote link,
   local file:/// executable link, and 17 detached screenshots.
   Must publish without aborting.
2. Secondary fail-open layer:
   Structured index failure (full and fallback) must NEVER abort core ZIP publication
   nor break clipboard handoff.
3. Residual path sanitizer:
   Share-safe mode transforms residual local paths without affecting remote URLs or relative paths.
4. Detached media blocks & evidence association:
   All 8 shapes from Section 82 (direct, adjacent_previous, adjacent_next, group, unscoped).
5. Deterministic invariant / fuzz corpus.
"""

import json
import os
import zipfile

import pytest

from fastprompter.core import silo_bundle as sb
from fastprompter.core import silo_index


@pytest.fixture
def dummy_png_factory(tmp_path):
    """Creates small real PNG files for bundling tests."""
    def _create(name: str) -> str:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        # Minimal valid 1x1 PNG bytes
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        p.write_bytes(png_bytes)
        return str(p)
    return _create


def test_t1416_operator_production_shape_publishes_reliably(tmp_path, dummy_png_factory):
    """Operator production failure regression:

    A real note containing:
      - H1 title and separators
      - Requirements A and B
      - Requirement C with prose paragraphs, https web link,
        file:/// executable link, and 17 detached screenshots.
    MUST publish successfully, preserve remote link, sanitize local exe path,
    package all 17 screenshots, and maintain index/manifest consistency.
    """
    img_paths = [dummy_png_factory(f"screen_{i:02d}.png") for i in range(1, 18)]

    img_refs_md = "\n".join(f"![screenshot {i}]({p.replace(os.sep, '/')})" for i, p in enumerate(img_paths, 1))

    # Synthetic Windows-shaped executable link
    exe_link = "file:///V:/private/tools/_WIN10_TWEAKER.exe"

    note_text = f"""# System Maintenance Silo
---
- REQ-001: Configure telemetry baseline
- REQ-002: Backup existing registry hives
---
- REQ-003: Apply automated optimizations
  Refer to upstream documentation at https://example.com/docs/tweaker?drive=C:/test
  Local utility archive: [Optimization Tool]({exe_link})
  Run the executable with administrative privileges and capture verification evidence.

  Screenshots:
{img_refs_md}
"""

    out_dir = str(tmp_path / "exports")
    os.makedirs(out_dir, exist_ok=True)

    plan = sb.plan_bundle(
        text=note_text,
        title="Maintenance Silo",
        target_dir=out_dir,
        hide_local_paths=True,
    )

    res = sb.write_bundle(plan)

    # 1. Primary product invariant: Packing MUST succeed
    assert res.zip_path is not None, f"write_bundle failed: {res.error}"
    assert os.path.isfile(res.zip_path)
    assert not res.error

    # 2. Inspect archive payload
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "README.txt" in namelist

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        readme = zf.read("README.txt").decode("utf-8")
        assert "Maintenance Silo" in readme

        # 17 images must all be present
        media_members = [m for m in namelist if m.startswith("media/")]
        assert len(media_members) == 17

        # Exported Markdown text must not leak absolute path
        md_members = [m for m in namelist if m.endswith(".md")]
        assert len(md_members) == 1
        exported_md = zf.read(md_members[0]).decode("utf-8")

        # Remote URL preserved
        assert "https://example.com/docs/tweaker?drive=C:/test" in exported_md

        # Absolute local path redacted
        assert "V:/private/tools" not in exported_md
        assert "file:///V:" not in exported_md
        # Label preserved with neutral omission note
        assert "Optimization Tool [local file omitted: _WIN10_TWEAKER.exe]" in exported_md or "[local file omitted: _WIN10_TWEAKER.exe]" in exported_md

        # Manifest metadata
        assert manifest.get("schema_version") >= 5
        assert manifest.get("index_status") in ("full", "degraded")
        assert manifest.get("bundle_status") in ("complete", "partial")

        # Check index if present
        if "silo.index.json" in namelist:
            idx = json.loads(zf.read("silo.index.json").decode("utf-8"))
            req3 = next(r for r in idx["requirements"] if r["id"] == "REQ-003")
            # All 17 screenshots associated with REQ-003 (either direct or adjacent_previous)
            assert len(req3["media"]) == 17
            assert "V:/private" not in json.dumps(idx)


def test_architectural_red_index_failure_never_blocks_zip_publication(tmp_path, dummy_png_factory, monkeypatch):
    """Architectural invariant: secondary index failure MUST NOT destroy primary archive.

    Force normal index generation to raise an exception,
    and force fallback index generation to raise an exception.
    The primary Markdown + media ZIP MUST still publish and report index_status: 'unavailable'.
    """
    img_path = dummy_png_factory("shot.png")
    note_text = f"""# Critical Work Note
- REQ-001: Operational requirement
  ![evidence]({img_path.replace(os.sep, '/')})
"""
    out_dir = str(tmp_path / "exports")
    os.makedirs(out_dir, exist_ok=True)

    plan = sb.plan_bundle(
        text=note_text,
        title="Critical Note",
        target_dir=out_dir,
        hide_local_paths=True,
    )

    # Monkeypatch both build_silo_index and build_fallback_index to simulate severe secondary failure
    def faulty_build_silo_index(*args, **kwargs):
        raise RuntimeError("Simulated severe parser crash in build_silo_index")

    def faulty_fallback_index(*args, **kwargs):
        raise RuntimeError("Simulated severe parser crash in build_fallback_index")

    monkeypatch.setattr(silo_index, "build_silo_index", faulty_build_silo_index)
    if hasattr(silo_index, "build_fallback_index"):
        monkeypatch.setattr(silo_index, "build_fallback_index", faulty_fallback_index)

    res = sb.write_bundle(plan)

    # Core invariant: ZIP must be created!
    assert res.zip_path is not None, f"write_bundle aborted on index failure: {res.error}"
    assert os.path.isfile(res.zip_path)

    with zipfile.ZipFile(res.zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "README.txt" in namelist
        # silo.index.json omitted because unavailable
        assert "silo.index.json" not in namelist

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest.get("index_status") == "unavailable"

        readme = zf.read("README.txt").decode("utf-8")
        assert "Structured index unavailable" in readme
        assert "Read the Markdown source directly" in readme


# ======================================================================
# Section 82: 8 Detached Screenshot Shapes (A..H)
# ======================================================================

def test_shape_a_interleaved_prose_and_screenshots(tmp_path, dummy_png_factory):
    """Shape A: requirement -> screenshot -> prose -> screenshot -> prose -> screenshot"""
    p1 = dummy_png_factory("a1.png")
    p2 = dummy_png_factory("a2.png")
    p3 = dummy_png_factory("a3.png")
    text = f"""- REQ-001: First requirement
  ![s1]({p1.replace(os.sep, '/')})
  Followup paragraph explaining step 1.
  ![s2]({p2.replace(os.sep, '/')})
  Another paragraph explaining step 2.
  ![s3]({p3.replace(os.sep, '/')})
"""
    plan = sb.plan_bundle(text=text, title="Shape A", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        assert "silo.index.json" in zf.namelist()
        idx = json.loads(zf.read("silo.index.json"))
        req = idx["requirements"][0]
        assert len(req["media"]) == 3


def test_shape_b_screenshot_before_requirement(tmp_path, dummy_png_factory):
    """Shape B: screenshot -> requirement (attaches via adjacent_next)"""
    p1 = dummy_png_factory("b1.png")
    text = f"""![header_shot]({p1.replace(os.sep, '/')})
- REQ-001: Target requirement
"""
    plan = sb.plan_bundle(text=text, title="Shape B", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        idx = json.loads(zf.read("silo.index.json"))
        req = idx["requirements"][0]
        assert len(req["media"]) == 1


def test_shape_c_requirement_a_shot_requirement_b_shot(tmp_path, dummy_png_factory):
    """Shape C: requirement A -> screenshot -> requirement B -> screenshot"""
    p1 = dummy_png_factory("c1.png")
    p2 = dummy_png_factory("c2.png")
    text = f"""- REQ-001: Alpha
  ![shot1]({p1.replace(os.sep, '/')})
- REQ-002: Beta
  ![shot2]({p2.replace(os.sep, '/')})
"""
    plan = sb.plan_bundle(text=text, title="Shape C", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        idx = json.loads(zf.read("silo.index.json"))
        assert idx["requirements"][0]["media"] == ["media/001_c1.png"]
        assert idx["requirements"][1]["media"] == ["media/002_c2.png"]


def test_shape_d_requirement_separator_screenshot_requirement(tmp_path, dummy_png_factory):
    """Shape D: requirement A -> separator -> screenshot -> requirement B
    Screenshot after separator should attach to requirement B (adjacent_next), not cross separator.
    """
    p1 = dummy_png_factory("d1.png")
    text = f"""- REQ-001: Alpha
---
![intro_shot]({p1.replace(os.sep, '/')})
- REQ-002: Beta
"""
    plan = sb.plan_bundle(text=text, title="Shape D", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        idx = json.loads(zf.read("silo.index.json"))
        assert idx["requirements"][0]["media"] == []
        assert idx["requirements"][1]["media"] == ["media/001_d1.png"]


def test_shape_e_heading_screenshots_paragraph(tmp_path, dummy_png_factory):
    """Shape E: heading -> screenshots -> paragraph"""
    p1 = dummy_png_factory("e1.png")
    text = f"""# Section Heading
![shot]({p1.replace(os.sep, '/')})

Descriptive paragraph of changes and verification.
"""
    plan = sb.plan_bundle(text=text, title="Shape E", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        idx = json.loads(zf.read("silo.index.json"))
        assert len(idx["requirements"]) == 1
        assert len(idx["requirements"][0]["media"]) == 1


def test_shape_f_screenshots_only(tmp_path, dummy_png_factory):
    """Shape F: screenshots only (unscoped media, no requirements)"""
    p1 = dummy_png_factory("f1.png")
    p2 = dummy_png_factory("f2.png")
    text = f"""![shot1]({p1.replace(os.sep, '/')})
![shot2]({p2.replace(os.sep, '/')})
"""
    plan = sb.plan_bundle(text=text, title="Shape F", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        idx = json.loads(zf.read("silo.index.json"))
        assert len(idx["requirements"]) == 0
        assert len(idx["unscoped_media"]) == 2


def test_shape_g_requirement_50_screenshots_eof(tmp_path, dummy_png_factory):
    """Shape G: requirement -> 50 screenshots -> EOF"""
    imgs = [dummy_png_factory(f"g_{i:02d}.png") for i in range(1, 51)]
    img_lines = "\n".join(f"![shot {i}]({p.replace(os.sep, '/')})" for i, p in enumerate(imgs, 1))
    text = f"""- REQ-001: Mega capture batch
Screenshots:
{img_lines}
"""
    plan = sb.plan_bundle(text=text, title="Shape G", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        media_files = [m for m in zf.namelist() if m.startswith("media/")]
        assert len(media_files) == 50
        idx = json.loads(zf.read("silo.index.json"))
        assert len(idx["requirements"][0]["media"]) == 50


def test_shape_h_several_requirements_shared_screenshot_block(tmp_path, dummy_png_factory):
    """Shape H: several requirements -> one shared screenshot block"""
    p1 = dummy_png_factory("h1.png")
    p2 = dummy_png_factory("h2.png")
    text = f"""- REQ-001: Item 1
- REQ-002: Item 2
- REQ-003: Item 3

Evidence for items 1-3:
![e1]({p1.replace(os.sep, '/')})
![e2]({p2.replace(os.sep, '/')})
"""
    plan = sb.plan_bundle(text=text, title="Shape H", target_dir=str(tmp_path / "exp"))
    res = sb.write_bundle(plan)
    assert res.zip_path is not None
    with zipfile.ZipFile(res.zip_path, "r") as zf:
        idx = json.loads(zf.read("silo.index.json"))
        assert len(idx["requirements"]) == 3
        # Group association preserved in media_evidence
        evs = idx.get("media_evidence", [])
        assert len(evs) == 2
        for ev in evs:
            assert ev["association"] in ("group", "adjacent_previous", "unscoped")


# ======================================================================
# Section 71 & 39: Local Path False Positive & Edge Cases
# ======================================================================

def test_local_path_false_positives_never_redacted():
    """Section 71: text phrases and remote URLs with drive-shaped params must not be redacted."""
    safe_texts = [
        "C: is the third option",
        "Select Option C: for default install",
        "file: metadata field format",
        "https://example.com/?next=C%3A&drive=D:/test",
        "http://intranet.local:8080/repo?path=C:\\projects\\app",
        "Installed software version 1.2.3 in test environment",
        "Safe relative path ./assets/icon.png",
    ]
    for text in safe_texts:
        sanitized, count = sb.sanitize_residual_local_paths(text)
        assert count == 0, f"False positive redaction on: {text!r} -> {sanitized!r}"
        assert sanitized == text
        assert not silo_index.contains_absolute_local_path(sanitized)


def test_real_absolute_paths_are_redacted():
    """True local absolute workstation paths are redacted deterministically."""
    leak_cases = [
        ("V:\\tools\\app.exe", "[local path omitted: app.exe]"),
        ("C:/Users/operator/secret.txt", "[local path omitted: secret.txt]"),
        ("\\\\server\\share\\docs\\report.pdf", "[local path omitted: report.pdf]"),
        ("file:///C:/Windows/notepad.exe", "[local path omitted: notepad.exe]"),
    ]
    for raw, expected in leak_cases:
        sanitized, count = sb.sanitize_residual_local_paths(raw)
        assert count >= 1
        assert expected in sanitized
        assert not silo_index.contains_absolute_local_path(sanitized)


# ======================================================================
# Section 78-80: Deterministic Invariant / Fuzz Corpus
# ======================================================================

def test_deterministic_fuzz_corpus_never_blocks_bundle(tmp_path, dummy_png_factory):
    """Section 78-80: 20 fixed-seed generated varied notes must all pack without crash."""
    import random
    rng = random.Random(42)

    imgs = [dummy_png_factory(f"fuzz_{i:02d}.png") for i in range(1, 10)]

    for i in range(20):
        lines = [f"# Fuzz Document {i}"]
        num_sections = rng.randint(1, 4)
        for s in range(num_sections):
            if rng.random() > 0.5:
                lines.append(rng.choice(["---", "***", "___"]))
            lines.append(f"## Section {s}")
            num_reqs = rng.randint(0, 5)
            for r in range(num_reqs):
                bullet = rng.choice(["-", "*", "+", "1.", "2)"])
                priority = rng.choice(["", " [P0]", " P1:", " (P2)", ""])
                lines.append(f"{bullet}{priority} Requirement {r} text details")
                if rng.random() > 0.4:
                    lines.append(f"  Continuation line with link https://example.com/item?id={r}")
                if rng.random() > 0.5:
                    chosen_img = rng.choice(imgs)
                    lines.append(f"  ![evidence]({chosen_img.replace(os.sep, '/')})")

            # Detached screenshot block
            if rng.random() > 0.4:
                lines.append("Screenshots:")
                for _ in range(rng.randint(1, 3)):
                    chosen_img = rng.choice(imgs)
                    lines.append(f"![detached]({chosen_img.replace(os.sep, '/')})")

        doc_text = "\n".join(lines)
        exp_dir = str(tmp_path / f"fuzz_exp_{i}")
        plan = sb.plan_bundle(text=doc_text, title=f"Fuzz_{i}", target_dir=exp_dir)
        res = sb.write_bundle(plan)

        # Global invariants (Section 79):
        assert res.zip_path is not None, f"Fuzz test {i} failed: {res.error}"
        assert os.path.isfile(res.zip_path)
        with zipfile.ZipFile(res.zip_path, "r") as zf:
            assert zf.testzip() is None
            names = zf.namelist()
            assert "manifest.json" in names
            assert "README.txt" in names
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["producer"] == "FastPrompter"
            assert manifest["schema_version"] >= 5
            for item in manifest.get("items", []):
                if item["status"] == "included":
                    assert item["member"] in names

