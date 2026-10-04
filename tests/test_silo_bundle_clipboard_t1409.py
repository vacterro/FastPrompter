"""T-1409 — the Pack backend: capture, worker, clipboard, notification.

The core oracle (pure ZIP/discovery maths) is proved in
``test_silo_bundle_core_t1409.py`` and the header geometry in
``test_silo_bundle_header_t1409.py``. This file covers the seam BETWEEN them:
what the window freezes at click time, what it hands the worker, what lands on
the clipboard, and what the user is told when something is missing.

The window here is a QWidget carrying the REAL ``FastPrompter`` Pack methods
and nothing else — so the code under test is the shipped code, not a
re-implementation of it. No real Desktop is touched: every path is a tmp_path.

Contract under test:
A  the click-time capture freezes the text, the silo folder and the
   destination, so a later edit or silo switch cannot retarget the bundle
B  capture refuses a snippet, an empty document and an unreachable folder
C  the title is the primary ``# `` heading; a fenced one never wins
D  a successful pack publishes the archive, copies the FILE to the clipboard,
   remembers the path, and leaves the silo's own text byte-identical
E  a partial pack still publishes and still copies, and says so in AMBER
F  a publication failure copies nothing and says the pack failed
G  a cancelled pack publishes nothing and says nothing
H  Copy Last Bundle is offered only while the remembered zip still exists
I  the Added-time and defaults stores round-trip as JSON, and the per-file
   selection is never persisted
"""

import os
import time
import zipfile
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from fastprompter import main as appmain
from fastprompter.core.state import _JSON_SETTINGS

_BACKEND = (
    "_bundle_app_version", "_silo_media_meta",
    "_silo_media_note_first_seen", "_silo_bundle_defaults",
    "_silo_bundle_remember_defaults", "_silo_bundle_capture",
    "_active_silo_bundle_context", "_silo_document_bound",
    "can_pack_active_silo",
    "silo_bundle_quick_pack", "silo_bundle_media_only",
    "silo_bundle_force_repack",
    "_silo_bundle_request", "_bundle_on_finished",
    "_silo_bundle_report_unavailable", "_reveal_path",
    "_silo_bundle_open_exports", "_silo_bundle_open_last_folder",
    "_silo_bundle_copy_last", "_silo_bundle_effective_options",
    "_silo_bundle_history", "_silo_bundle_history_candidates",
    "_silo_bundle_last_existing", "_silo_bundle_record_success",
    "_silo_bundle_apply_retention",
)


class _Win(QWidget):
    """The shipped Pack backend on a bare window.

    Every method is grafted from ``FastPrompter`` unchanged, so a behaviour
    that existed only in this file would fail here rather than pass.
    """


for _name in _BACKEND:
    setattr(_Win, _name, getattr(appmain.FastPrompter, _name))

# A staticmethod has to be re-wrapped as one, or grafting it would turn it
# into an instance method and silently change its signature.
_Win._silo_bundle_title = staticmethod(
    appmain.FastPrompter.__dict__["_silo_bundle_title"].__func__)


_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _png(folder, name):
    full = os.path.join(str(folder), name)
    with open(full, "wb") as fh:
        fh.write(_PNG)
    return full


def _url(path):
    return "file:///" + path.replace("\\", "/")


def _body(path):
    """A silo document whose only media is one inline reference."""
    return f"# My Silo\n\n![]({_url(path)})\n"


@pytest.fixture()
def win(tmp_path, qapp):
    silo_dir = tmp_path / "silo"
    silo_dir.mkdir()
    # The clipboard is process-wide: a leftover file URL from an earlier test
    # would otherwise read as "this test put something there".
    QApplication.clipboard().clear()
    w = _Win()
    w.data = {}
    w.text = "# My Silo\n\nsome body text\n"
    w.active_temp_slot = 0
    w.active_is_archive = False
    w.editing_snippet = False
    w._current_lang = "EN"
    w.silo_dir = str(silo_dir)
    w.toasts = []
    w._last_bundle_path = None
    w._bundle_ops = {}
    w._bundle_version_cache = ""

    w._editor_text_snapshot = lambda: w.text
    w._silo_folder_dir = lambda slot, is_archive=False: w.silo_dir
    # T-1410: admission is now a DOCUMENT-OWNERSHIP question, not a
    # folder-exists one. This window has no live editor document to check,
    # so the ownership predicate is stubbed True here; the cases that turn
    # it False live in test_silo_bundle_admission_t1410.py, and a real
    # window answers it through `_document_owner_matches`.
    w._silo_document_bound = lambda slot, is_archive: True
    w._active_silo_id = lambda: "silo-A"
    w.get_current_category = lambda: "Notes"
    w.save_data_to_db = lambda *a, **k: True
    w._show_in_app_toast = (
        lambda title, message, **kw: w.toasts.append((title, message, kw)))
    yield w
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _run(win, options=None):
    """Start one pack and pump the GUI loop until its result has landed."""
    op = win._silo_bundle_request(options)
    assert op is not None
    deadline = time.time() + 20.0
    while time.time() < deadline:
        QApplication.processEvents()
        # The registry empties on `finished`, which is emitted before the
        # worker's own event loop stops; wait for the thread too, or teardown
        # races the QThread destructor.
        if id(op) not in win._bundle_ops and not op.thread.isRunning():
            return op
        time.sleep(0.01)
    QApplication.processEvents()
    assert id(op) not in win._bundle_ops, "the bundle never finished"
    return op


def _members(path):
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def _clipboard_urls():
    mime = QApplication.clipboard().mimeData()
    if mime is None:
        return []
    return [os.path.normpath(u.toLocalFile()) for u in mime.urls()]


# --- A: click-time capture ------------------------------------------------

def test_capture_freezes_the_click_time_text(win):
    cap = win._silo_bundle_capture()
    assert cap["plan_kwargs"]["text"] == win.text
    win.text = "# Rewritten\n"
    assert cap["plan_kwargs"]["text"] == "# My Silo\n\nsome body text\n"


def test_capture_freezes_the_silo_folder_and_destination(win, tmp_path):
    cap = win._silo_bundle_capture()
    assert cap["silo_dir"] == win.silo_dir
    assert cap["target_dir"] == os.path.join(win.silo_dir, "exports")
    assert cap["plan_kwargs"]["target_dir"] == cap["target_dir"]
    win.silo_dir = str(tmp_path / "other")     # a silo switch, mid-flight
    assert cap["silo_dir"] == str(tmp_path / "silo")
    assert cap["plan_kwargs"]["silo_dir"] == str(tmp_path / "silo")


def test_capture_honours_an_explicit_destination(win, tmp_path):
    elsewhere = str(tmp_path / "dest")
    cap = win._silo_bundle_capture({"target_dir": elsewhere})
    assert cap["target_dir"] == elsewhere
    assert cap["plan_kwargs"]["target_dir"] == elsewhere


def test_capture_names_the_captured_silo(win):
    assert win._silo_bundle_capture()["title"] == "My Silo"


# --- B: capture refuses ---------------------------------------------------

def test_capture_admits_an_empty_document_because_admission_is_not_emptiness(win):
    """T-1410 split this in two, and it is worth saying why.

    It used to assert that blank text makes ``_silo_bundle_capture`` return
    None — which conflated two different questions. Whether a silo is open
    is a property of the editor's document binding; whether anything is
    worth putting in an archive is a property of the plan. A silo can be
    perfectly open and hold nothing but media, so an empty document must
    still be admitted here.

    The refusal this file used to imply now belongs to the plan, and
    ``test_silo_bundle_admission_t1410.py`` proves it is truthful: a silo
    with no text, no media and no attachments packs to "Nothing to pack".
    """
    win.text = "   \n\n"
    assert win._silo_bundle_capture() is not None


def test_capture_refuses_snippet_mode(win):
    win.editing_snippet = True
    assert win._silo_bundle_capture() is None


def test_capture_refuses_a_storage_root_that_cannot_be_resolved(win):
    """T-1410 replaced this test, and it is worth saying why.

    It used to prove "invalid silo" with a path that merely did not exist on
    disk — which encoded the production bug, because a silo folder is LAZY
    and a real silo with no folder yet is the normal case, not an invalid
    one. Absence of the folder is no longer a refusal at all
    (``test_silo_bundle_admission_t1410.py`` proves the pack succeeds).

    What genuinely is a refusal is a storage root the app cannot resolve a
    folder name under, because that one can never be created for the user.
    """
    win._silo_folder_dir = lambda slot, is_archive=False: None
    assert win._silo_bundle_capture() is None
    assert win._silo_bundle_request() is None
    assert win.toasts and win.toasts[-1][0] == "Silo storage is unavailable"


# --- C: title -------------------------------------------------------------

def test_title_is_the_primary_header(win):
    assert win._silo_bundle_title(
        "intro line\n# Real Title\n") == "Real Title"


def test_title_ignores_a_fenced_hash_line(win):
    assert win._silo_bundle_title(
        "# Real Title\n```\n# not a heading\n```\n") == "Real Title"


def test_title_falls_back_to_the_first_line(win):
    # A ``# `` heading anywhere wins — it is the same header the Pack button
    # is painted on, and the archive must name what the user sees.
    assert win._silo_bundle_title("just a note\n\n# later\n") == "later"
    assert win._silo_bundle_title("just a note\nmore") == "just a note"
    assert win._silo_bundle_title("") == "silo"


# --- D: a successful pack -------------------------------------------------

def test_quick_pack_publishes_copies_and_remembers(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)
    before = win.text

    _run(win)

    zip_path = win._last_bundle_path
    assert zip_path and os.path.isfile(zip_path)
    assert os.path.dirname(zip_path) == os.path.join(win.silo_dir, "exports")
    assert os.path.basename(zip_path).startswith("My Silo_bundle_")
    names = _members(zip_path)
    assert "My Silo.md" in names and "manifest.json" in names
    assert any(n.startswith("media/") and n.endswith(".png") for n in names)
    assert _clipboard_urls() == [zip_path]
    assert win.text == before, "the original silo text must not be modified"
    assert win.toasts and win.toasts[-1][0] == "Silo packed"


def test_bundled_markdown_points_at_the_in_archive_member(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)
    _run(win)
    with zipfile.ZipFile(win._last_bundle_path) as zf:
        body = zf.read("My Silo.md").decode("utf-8")
    assert "media/" in body
    assert "V:" not in body and "file:///" not in body


def test_successful_pack_offers_open_folder_and_copy_again(win):
    _run(win)
    labels = [label for label, _cb in win.toasts[-1][2]["actions"]]
    assert labels == ["Open folder", "Copy again"]


def test_two_packs_in_a_row_never_clobber_each_other(win):
    _run(win)
    _run(win, {"force_repack": True})
    bundles = os.listdir(os.path.join(win.silo_dir, "exports"))
    assert len(bundles) == 2
    assert all(b.endswith(".zip") for b in bundles)


def test_exports_folder_is_excluded_from_the_bundle(win):
    _run(win)
    _run(win)
    with zipfile.ZipFile(win._last_bundle_path) as zf:
        assert not [n for n in zf.namelist() if "exports" in n]


# --- E: a partial pack ----------------------------------------------------

def test_missing_source_publishes_and_still_copies(win):
    gone = os.path.join(win.silo_dir, "gone.png")   # referenced, never created
    win.text = _body(gone)

    _run(win)

    zip_path = win._last_bundle_path
    assert zip_path and os.path.isfile(zip_path)
    assert _clipboard_urls() == [zip_path]
    title, _message, kw = win.toasts[-1]
    assert title == "Silo packed"
    assert "Partial bundle" in kw["status"]
    assert kw["accent_color"] == "#e0a03c"


# --- F: a publication failure ---------------------------------------------

def test_unpublishable_destination_fails_without_touching_the_clipboard(win):
    blocker = os.path.join(win.silo_dir, "blocker")
    with open(blocker, "wb") as fh:
        fh.write(b"not a directory")

    _run(win, {"target_dir": os.path.join(blocker, "sub")})

    assert win._last_bundle_path is None
    assert _clipboard_urls() == []
    title, _message, kw = win.toasts[-1]
    assert title == "Silo not packed"
    assert "clipboard" in _message


# --- G: cancellation ------------------------------------------------------

def test_cancelled_pack_publishes_nothing_and_says_nothing(win):
    op = win._silo_bundle_request()
    op.capture["cancel"].set()
    deadline = time.time() + 20.0
    while time.time() < deadline:
        QApplication.processEvents()
        if id(op) not in win._bundle_ops and not op.thread.isRunning():
            break
        time.sleep(0.01)
    assert id(op) not in win._bundle_ops
    assert win._last_bundle_path is None
    assert win.toasts == []
    exports = os.path.join(win.silo_dir, "exports")
    if os.path.isdir(exports):
        # The folder itself may be created before the first cancel check; what
        # must not exist is a published archive.
        assert not [n for n in os.listdir(exports) if n.endswith(".zip")]


# --- H: Copy Last Bundle --------------------------------------------------

def test_copy_last_bundle_needs_the_file_to_still_exist(win):
    _run(win)
    assert win._last_bundle_path and os.path.isfile(win._last_bundle_path)
    win._silo_bundle_copy_last()
    assert _clipboard_urls() == [win._last_bundle_path]
    os.remove(win._last_bundle_path)
    win._silo_bundle_copy_last()          # must not raise, must not resurrect
    assert not os.path.exists(win._last_bundle_path)


def test_open_exports_creates_the_folder_it_opens(win, monkeypatch):
    opened = []
    monkeypatch.setattr(appmain.os, "startfile", lambda p: opened.append(p))
    target = os.path.join(win.silo_dir, "exports")
    assert not os.path.isdir(target)
    win._silo_bundle_open_exports()
    assert os.path.isdir(target)
    assert opened == [target]


def _menu(win):
    from fastprompter.ui.silo_bundle_actions import build_bundle_menu
    calls = []
    editor = SimpleNamespace(
        main_win=win,
        _silo_bundle_dispatch_fallback=lambda *_: calls.append("quick"),
        _silo_bundle_dispatch_with_options=lambda *_: calls.append("options"),
    )
    menu = QMenu()
    build_bundle_menu(editor, menu, "EN")
    actions = {a.text(): a for a in menu.actions() if a.text()}
    return menu, actions, calls


def test_menu_copy_last_is_disabled_until_a_bundle_exists(win):
    _menu_stub = SimpleNamespace(_silo_bundle_open_exports=lambda: None,
                                 _silo_bundle_copy_last=lambda: None,
                                 _silo_bundle_open_last_folder=lambda: None,
                                 silo_bundle_force_repack=lambda: None,
                                 silo_bundle_media_only=lambda: None)
    _menu_stub._last_bundle_path = None
    from fastprompter.ui.silo_bundle_actions import build_bundle_menu
    editor = SimpleNamespace(
        main_win=_menu_stub,
        _silo_bundle_dispatch_fallback=lambda *_: None,
        _silo_bundle_dispatch_with_options=lambda *_: None,
    )
    menu = QMenu()
    build_bundle_menu(editor, menu, "EN")
    states = {a.text(): a.isEnabled() for a in menu.actions() if a.text()}
    assert states["Copy Last Bundle"] is False
    assert states["Open Last Bundle Folder"] is False
    assert states["Quick Pack"] is True
    assert states["Pack Silo With Options…"] is True
    assert states["Force Repack"] is True
    assert states["Open Silo Exports Folder"] is True
    assert states["Media-Only Quick Pack"] is True


def test_menu_copy_last_is_enabled_while_the_zip_exists(win):
    _run(win)
    editor = SimpleNamespace(
        main_win=win,
        _silo_bundle_dispatch_fallback=lambda *_: None,
        _silo_bundle_dispatch_with_options=lambda *_: None,
    )
    from fastprompter.ui.silo_bundle_actions import build_bundle_menu
    menu = QMenu()
    build_bundle_menu(editor, menu, "EN")
    states = {a.text(): a.isEnabled() for a in menu.actions() if a.text()}
    assert states["Copy Last Bundle"] is True
    assert states["Open Last Bundle Folder"] is True
    os.remove(win._last_bundle_path)
    menu2 = QMenu()
    build_bundle_menu(editor, menu2, "EN")
    states2 = {a.text(): a.isEnabled() for a in menu2.actions() if a.text()}
    assert states2["Copy Last Bundle"] is False
    assert states2["Open Last Bundle Folder"] is False


def test_media_only_pack_carries_no_markdown(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)
    _run(win, {"media_only": True})
    with zipfile.ZipFile(win._last_bundle_path) as zf:
        assert "My Silo.md" not in zf.namelist()
        assert any(n.startswith("media/") for n in zf.namelist())
    assert win.text.startswith("# My Silo")   # still untouched


# --- I: durable stores ----------------------------------------------------

def test_added_time_store_is_json_registered():
    assert "silo_media_first_seen" in _JSON_SETTINGS
    assert "silo_bundle_defaults" in _JSON_SETTINGS


def test_media_meta_is_recorded_once_and_never_overwritten(win):
    shot = _png(win.silo_dir, "shot.png")
    win._silo_media_note_first_seen("silo-A", [shot])
    first = win._silo_media_meta("silo-A")[os.path.normcase(
        os.path.realpath(shot))]
    win._silo_media_note_first_seen("silo-A", [shot])
    assert win._silo_media_meta("silo-A")[os.path.normcase(
        os.path.realpath(shot))] == first


def test_media_meta_is_scoped_to_one_silo_and_survives_bad_rows(win):
    shot = _png(win.silo_dir, "shot.png")
    win.data["silo_media_first_seen"] = {"silo-A": {"x": "not-a-number"}}
    assert win._silo_media_meta("silo-A") == {}
    win._silo_media_note_first_seen("silo-B", [shot])
    assert win._silo_media_meta("silo-A") == {}
    assert len(win._silo_media_meta("silo-B")) == 1


def test_media_meta_reaches_the_bundle_plan(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)
    win._silo_media_note_first_seen("silo-A", [shot])
    _run(win)
    import json
    with zipfile.ZipFile(win._last_bundle_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    entry = manifest["items"][0]
    assert entry["added_source"] == "silo_metadata"
    assert entry["added_at"]


def test_remembered_defaults_round_trip_and_drop_the_selection(win):
    win._silo_bundle_remember_defaults("silo-A", {
        "include_text": True, "include_attachments": False,
        "hide_local_paths": True, "destination": "silo",
        "selected": ["a.png", "b.png"],
    })
    stored = win.data["silo_bundle_defaults"]["silo-A"]
    assert "selected" not in stored
    assert stored["destination"] == "silo"
    assert win._silo_bundle_defaults("silo-A")["include_attachments"] is False


def test_defaults_for_an_unknown_silo_are_empty_not_an_error(win):
    assert win._silo_bundle_defaults("nope") == {}
    win._silo_bundle_remember_defaults(None, {"include_text": True})
    assert win.data.get("silo_bundle_defaults", {}) == {}


# --- app version ----------------------------------------------------------

def test_manifest_records_the_app_version_field(win):
    win._bundle_version_cache = "9.9.9"
    _run(win)
    import json
    with zipfile.ZipFile(win._last_bundle_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["app_version"] == "9.9.9"
    assert manifest["schema_version"] in (1, 2, 3, 4)


def test_app_version_is_cached_and_never_raises(tmp_path):
    from fastprompter.main import FastPrompter
    stub = SimpleNamespace(_bundle_version_cache=None)
    assert FastPrompter._bundle_app_version(stub) == stub._bundle_version_cache
