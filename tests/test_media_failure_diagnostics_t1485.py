"""T-1485: Reading-mode media failures must keep the reason they came with.

The T-1484 suite pinned ``set_failed``'s notes table and the local ``OSError``
path, but nothing ever drove ``_on_remote_failed`` -- the callback the loader
actually calls -- so the production path could drop every cause into an
anonymous box and stay green.  These tests drive that path directly: no
transport is opened (the block is seeded in its external-media-off state, which
is exactly the state a pre-fix build leaves behind), and the assertion is on the
cause the block ends up carrying.
"""

from __future__ import annotations

import logging

import pytest
from PyQt6.QtWidgets import QApplication

from fastprompter.core import rich_preview
from fastprompter.ui import rich_preview_view as view_module
from fastprompter.ui.rich_preview_view import RichPreviewView

ONLINE = "https://cdn.example/a.png?Signature=SECRET123"


def _block(view, url):
    """A remote block registered on the view, without opening a request."""
    view.configure(external_media=False)
    block = view_module._MediaBlock(
        view, rich_preview.MediaRef(url=url, remote=True))
    view._media_blocks.setdefault(url, []).append(block)
    return block


def _note(cause):
    return view_module._MEDIA_NOTES[cause]


@pytest.fixture
def view(qapp):
    surface = RichPreviewView()
    surface.resize(320, 240)
    surface.show()
    QApplication.processEvents()
    yield surface
    surface.deleteLater()
    QApplication.processEvents()


def test_a_policy_refusal_reaches_the_block_as_its_own_cause(view):
    block = _block(view, ONLINE)
    view._on_remote_failed(ONLINE, "policy refuses host cdn.example")

    assert block._cause == view_module.MEDIA_CAUSE_REFUSED
    assert _note(view_module.MEDIA_CAUSE_REFUSED) in block.text()


def test_a_transfer_failure_names_the_transfer(view):
    block = _block(view, ONLINE)
    view._on_remote_failed(ONLINE, "timeout after 10s")

    assert block._cause == view_module.MEDIA_CAUSE_TRANSFER
    assert _note(view_module.MEDIA_CAUSE_TRANSFER) in block.text()


def test_a_size_cap_reply_names_oversizing(view):
    block = _block(view, ONLINE)
    view._on_remote_failed(ONLINE, "size cap 20971520 exceeded")

    assert block._cause == view_module.MEDIA_CAUSE_OVERSIZED
    assert _note(view_module.MEDIA_CAUSE_OVERSIZED) in block.text()


def test_the_three_remote_outcomes_do_not_render_the_same_box(view):
    refused = _block(view, ONLINE)
    transfer = _block(view, "https://cdn.example/b.png")
    oversized = _block(view, "https://cdn.example/c.png")
    view._on_remote_failed(ONLINE, "policy refuses host")
    view._on_remote_failed("https://cdn.example/b.png", "connection reset")
    view._on_remote_failed("https://cdn.example/c.png", "size cap exceeded")

    texts = {refused.text(), transfer.text(), oversized.text()}
    assert len(texts) == 3, (
        "three different failures must not collapse into one placeholder")


def test_the_reason_is_logged_without_the_url_token(view, caplog):
    block = _block(view, ONLINE)
    with caplog.at_level(logging.WARNING):
        view._on_remote_failed(ONLINE, "timeout after 10s")

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "SECRET123" not in joined, (
        "a signed CDN query string must never be copied into the log")
    assert "cdn.example/a.png" in joined
    assert view_module.MEDIA_CAUSE_TRANSFER in joined
    assert "timeout after 10s" in joined


def test_a_reply_arriving_after_suspend_is_ignored(view):
    block = _block(view, ONLINE)
    before = block.text()
    view.suspend_media()
    view._on_remote_failed(ONLINE, "policy refuses host")
    assert block.text() == before, (
        "a stale failure must not rewrite a surface nobody is looking at")
    view.resume_media()


def test_an_unreadable_local_file_names_the_local_cause(view, tmp_path):
    block = view_module._MediaBlock(
        view, rich_preview.MediaRef(url=str(tmp_path / "gone.png")))
    assert block._cause == view_module.MEDIA_CAUSE_LOCAL
    assert _note(view_module.MEDIA_CAUSE_LOCAL) in block.text()
