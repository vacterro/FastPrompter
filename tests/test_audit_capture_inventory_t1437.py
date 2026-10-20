"""T-1437 (SRC-097) — PERF-005: image dimensions come from a non-widget probe.

``plan_bundle`` discovers dimensions through a plain ``QImageReader`` header
read, so the whole capture runs on the bundle WORKER thread and no widget is
ever touched. A format the plugins cannot read yields no dimension, not an
error.
"""

from __future__ import annotations


def _dimensions():
    # imported in-test so the red control fails at the assertion, not collection
    from fastprompter.main import _bundle_image_dimensions
    return _bundle_image_dimensions


def test_perf_005_dimensions_from_a_real_image(tmp_path, qapp):
    from PyQt6.QtGui import QImage

    _bundle_image_dimensions = _dimensions()
    p = tmp_path / "shot.png"
    img = QImage(7, 3, QImage.Format.Format_RGB32)
    assert img.save(str(p), "PNG") is True

    assert _bundle_image_dimensions(str(p)) == {"width": 7, "height": 3}


def test_perf_005_no_dimensions_for_a_non_image(tmp_path):
    _bundle_image_dimensions = _dimensions()
    p = tmp_path / "notes.txt"
    p.write_text("not an image", encoding="utf-8")

    assert _bundle_image_dimensions(str(p)) is None


def test_perf_005_no_dimensions_for_a_missing_path(tmp_path):
    _bundle_image_dimensions = _dimensions()
    assert _bundle_image_dimensions(str(tmp_path / "absent.png")) is None
