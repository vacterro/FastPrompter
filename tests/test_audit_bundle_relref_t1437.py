"""T-1437 (SRC-097) — W2-002: ONE reference-resolution context per plan.

Planning resolves relative document references against the silo/base
directory. Publication must reuse the SAME authority (``plan.reference_base_dir``
through ``plan_refs``), or a relative reference valid at plan time becomes
"missing" at write time while its bytes are archived anyway -- a ZIP that
contradicts itself and whose fingerprint differs from the preflight one.
"""

from __future__ import annotations

from fastprompter.core import silo_bundle as sb


def _plan(**kw):
    base = dict(archive_name="Sil", display_title="Sil", category="Cat",
                target_dir="", text_member="Sil.md", text_body="")
    base.update(kw)
    return sb.BundlePlan(**base)


def test_w2_002_plan_refs_resolves_against_the_recorded_base(tmp_path):
    d = tmp_path / "silo"
    d.mkdir()
    (d / "asset.png").write_bytes(b"x")
    text = "![asset](asset.png)"

    with_base = _plan(origin_text=text, reference_base_dir=str(d))
    refs = sb.plan_refs(with_base)
    assert len(refs) == 1
    assert refs[0].kind == "relative"
    assert refs[0].path == str(d / "asset.png")
    # identical to resolving the same text with the same base directly
    assert [r.path for r in refs] == [
        r.path for r in sb.find_local_refs(text, str(d))]


def test_w2_002_without_a_base_a_relative_ref_stays_unresolved():
    plan = _plan(origin_text="![asset](asset.png)", reference_base_dir="")
    refs = sb.plan_refs(plan)
    assert len(refs) == 1
    assert refs[0].kind == "relative"
    assert refs[0].path is None


def test_w2_002_plan_bundle_records_base_dir_then_silo_dir(tmp_path):
    base = tmp_path / "base"
    silo = tmp_path / "silo"
    base.mkdir()
    silo.mkdir()

    with_base = sb.plan_bundle(text="# t\n", title="Sil", target_dir=str(tmp_path),
                               base_dir=str(base), silo_dir=str(silo))
    assert with_base.reference_base_dir == str(base)

    without_base = sb.plan_bundle(text="# t\n", title="Sil", target_dir=str(tmp_path),
                                  silo_dir=str(silo))
    assert without_base.reference_base_dir == str(silo)

    neither = sb.plan_bundle(text="# t\n", title="Sil", target_dir=str(tmp_path))
    assert neither.reference_base_dir == ""
