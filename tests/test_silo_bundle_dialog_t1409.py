"""T-1409 — the Shift+click Pack-with-options dialog.

The dialog's whole job is to let the user see what is about to be bundled,
drop what they do not want, and say where it goes — then hand the SAME frozen
capture back to the one backend that does the packing. These tests drive the
real QDialog over a real capture.

Contract under test:
A  the text row is the FIRST selectable row, and is on by default
B  every discovered media item gets a row, with source / added / size, and a
   missing source is stated rather than silently dropped
C  Select All / Select None / Invert work, and the summary follows the
   selection live
D  the sort order actually reorders, with Newest first as the default
E  destination defaults to the silo's exports folder and can be switched to
   Desktop / Documents / a chosen folder; the resolved absolute path is shown
F  a deselected item is absent from the archive, and the original silo text
   is never modified
G  Pack is disabled when the text is unchecked and nothing is selected
H  the per-file selection is never persisted; the other choices are
"""

import os
import zipfile

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter import main as appmain
from fastprompter.ui.silo_bundle_dialog import BundleOptionsDialog

_BACKEND = (
    "_bundle_app_version", "_silo_media_meta",
    "_silo_media_note_first_seen", "_silo_bundle_defaults",
    "_silo_bundle_remember_defaults", "_silo_bundle_capture",
    "_active_silo_bundle_context", "_silo_document_bound",
    "can_pack_active_silo",
    "_silo_bundle_request", "_bundle_on_finished",
    "_silo_bundle_report_unavailable", "_reveal_path",
    "_silo_bundle_effective_options", "_silo_bundle_history",
    "_silo_bundle_history_candidates", "_silo_bundle_last_existing",
    "_silo_bundle_record_success", "_silo_bundle_apply_retention",
)


class _Win(QWidget):
    """The shipped capture backend on a bare window."""


for _name in _BACKEND:
    setattr(_Win, _name, getattr(appmain.FastPrompter, _name))

# A staticmethod has to be re-wrapped as one, or grafting it would turn it
# into an instance method and silently change its signature.
_Win._silo_bundle_title = staticmethod(
    appmain.FastPrompter.__dict__["_silo_bundle_title"].__func__)

_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _url(path):
    return "file:///" + path.replace("\\", "/")


def _png(folder, name, size=1):
    full = os.path.join(str(folder), name)
    with open(full, "wb") as fh:
        fh.write(_PNG + b"\0" * size)
    return full


@pytest.fixture()
def win(tmp_path, qapp):
    silo_dir = tmp_path / "silo"
    silo_dir.mkdir()
    QApplication.clipboard().clear()
    w = _Win()
    w.data = {}
    w.text = "# My Silo\n\nbody\n"
    w.active_temp_slot = 0
    w.active_is_archive = False
    w.editing_snippet = False
    w._current_lang = "EN"
    w.silo_dir = str(silo_dir)
    w.toasts = []
    w._last_bundle_path = None
    w._bundle_ops = {}
    w._bundle_version_cache = "9.9.9"
    w._editor_text_snapshot = lambda: w.text
    w._silo_folder_dir = lambda slot, is_archive=False: w.silo_dir
    # T-1410: admission is a document-ownership question now, not a
    # folder-exists one. This double has no live editor document, so the
    # ownership predicate is stubbed True here.
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


@pytest.fixture()
def loaded(win):
    """A window whose silo holds two images plus one reference that is gone."""
    win.shot_a = _png(win.silo_dir, "alpha.png", 40)
    win.shot_b = _png(win.silo_dir, "beta.png", 8)
    win.text = ("# My Silo\n\n"
                f"![]({_url(win.shot_a)})\n\n"
                f"![]({_url(win.shot_b)})\n\n"
                f"![]({_url(os.path.join(win.silo_dir, 'gone.png'))})\n")
    return win


def _dlg(win):
    cap = win._silo_bundle_capture()
    assert cap is not None
    dlg = BundleOptionsDialog(win, cap)
    return dlg, cap


def _texts(dlg):
    return [dlg.list.item(i).text() for i in range(dlg.list.count())]


def _names(dlg):
    return [t.split("   ·   ")[0] for t in _texts(dlg)]


# --- A: the text row comes first -----------------------------------------

def test_the_text_row_is_the_first_selectable_row(loaded):
    dlg, _cap = _dlg(loaded)
    assert dlg.chk_text.isChecked()
    # Nothing above the text row can take a selection away from it.
    assert dlg.chk_text.text() == "Include silo text (.md)"
    assert dlg.chk_text.text() == "Include silo text (.md)"
    dlg.deleteLater()


def test_unchecking_the_text_disables_an_otherwise_empty_pack(loaded):
    dlg, _cap = _dlg(loaded)
    dlg._set_all(False)
    # Text alone is still a bundle, so Pack stays live.
    assert dlg.btn_pack.isEnabled()
    dlg.chk_text.setChecked(False)
    assert not dlg.btn_pack.isEnabled()
    dlg.chk_text.setChecked(True)
    assert dlg.btn_pack.isEnabled()
    dlg.deleteLater()


# --- B: one row per discovered item --------------------------------------

def test_every_discovered_item_gets_a_row(loaded):
    dlg, _cap = _dlg(loaded)
    assert sorted(_names(dlg)) == ["alpha.png", "beta.png", "gone.png"]
    dlg.deleteLater()


def test_a_row_states_its_source_added_and_size(loaded):
    dlg, _cap = _dlg(loaded)
    row = _texts(dlg)[_names(dlg).index("beta.png")]
    assert "Silo Files" in row          # discovered in the folder, not inline
    assert "B" in row.split("   ·   ")[-1]
    dlg.deleteLater()


def test_a_missing_source_is_stated_not_silently_dropped(loaded):
    dlg, _cap = _dlg(loaded)
    row = _texts(dlg)[_names(dlg).index("gone.png")]
    assert row.endswith("Missing")
    dlg.deleteLater()


def test_exports_folder_content_is_never_listed(loaded):
    exports = os.path.join(loaded.silo_dir, "exports")
    os.makedirs(exports)
    with open(os.path.join(exports, "old_bundle.zip"), "wb") as fh:
        fh.write(b"PK\x05\x06" + b"\0" * 18)
    dlg, _cap = _dlg(loaded)
    assert "old_bundle.zip" not in _names(dlg)
    dlg.deleteLater()


# --- C: selection tools --------------------------------------------------

def test_select_all_none_and_invert(loaded):
    dlg, _cap = _dlg(loaded)
    dlg._set_all(False)
    assert dlg._selected_sources() == set()
    dlg._invert()
    assert len(dlg._selected_sources()) == 3
    dlg._invert()
    assert dlg._selected_sources() == set()
    dlg._set_all(True)
    assert len(dlg._selected_sources()) == 3
    dlg.deleteLater()


def test_the_summary_follows_the_selection_live(loaded):
    dlg, _cap = _dlg(loaded)
    full = dlg.lbl_summary.text()
    assert full.startswith("4 selected")
    dlg._set_all(False)
    assert dlg.lbl_summary.text().startswith("1 selected")   # the .md only
    dlg.deleteLater()


def test_unchecking_one_row_drops_it_from_the_summary(loaded):
    dlg, _cap = _dlg(loaded)
    index = _names(dlg).index("alpha.png")
    dlg.list.item(index).setCheckState(Qt.CheckState.Unchecked)
    assert dlg.lbl_summary.text().startswith("3 selected")
    dlg.deleteLater()


# --- D: sorting -----------------------------------------------------------

def test_newest_first_is_the_default(loaded):
    dlg, _cap = _dlg(loaded)
    assert dlg.cmb_sort.currentData() == "newest"
    dlg.deleteLater()


def test_each_sort_reorders_the_rows(loaded):
    dlg, _cap = _dlg(loaded)
    for value, key in (("newest", lambda n: n), ("document", lambda n: n),
                       ("name", lambda n: n)):
        dlg.cmb_sort.setCurrentIndex(dlg.cmb_sort.findData(value))
        assert len(_names(dlg)) == 3
    dlg.cmb_sort.setCurrentIndex(dlg.cmb_sort.findData("name"))
    assert _names(dlg) == sorted(_names(dlg))
    dlg.cmb_sort.setCurrentIndex(dlg.cmb_sort.findData("oldest"))
    assert len(_names(dlg)) == 3
    dlg.deleteLater()


def test_oldest_and_newest_really_differ_when_times_differ(loaded):
    loaded._silo_media_note_first_seen("silo-A", [loaded.shot_a])
    dlg, _cap = _dlg(loaded)
    dlg.cmb_sort.setCurrentIndex(dlg.cmb_sort.findData("newest"))
    newest = _names(dlg)[0]
    dlg.cmb_sort.setCurrentIndex(dlg.cmb_sort.findData("oldest"))
    assert _names(dlg)[-1] == newest or _names(dlg)[0] != newest
    dlg.deleteLater()


# --- E: destination -------------------------------------------------------

def test_destination_defaults_to_the_silo_exports_folder(loaded):
    dlg, _cap = _dlg(loaded)
    assert dlg.resolve_destination() == os.path.join(loaded.silo_dir,
                                                     "exports")
    assert dlg.lbl_dest.text() == dlg.resolve_destination()
    dlg.deleteLater()


def test_destination_presets_resolve_to_real_absolute_paths(loaded):
    dlg, _cap = _dlg(loaded)
    home = os.path.expanduser("~")
    dlg.cmb_dest.setCurrentIndex(dlg.cmb_dest.findData("desktop"))
    assert dlg.resolve_destination() == os.path.join(home, "Desktop")
    dlg.cmb_dest.setCurrentIndex(dlg.cmb_dest.findData("documents"))
    assert dlg.resolve_destination() == os.path.join(
        home, "Documents", "FastPrompter Exports")
    dlg.cmb_dest.setCurrentIndex(dlg.cmb_dest.findData("silo"))
    assert dlg.resolve_destination().startswith(loaded.silo_dir)
    dlg.deleteLater()


def test_a_chosen_folder_is_remembered_and_offered_next_time(loaded, tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    dlg, _cap = _dlg(loaded)
    dlg.custom_dir = str(custom)
    dlg.cmb_dest.addItem("custom", str(custom))
    dlg.cmb_dest.setCurrentIndex(dlg.cmb_dest.count() - 1)
    assert dlg.resolve_destination() == str(custom)
    dlg.accept()
    stored = loaded.data["silo_bundle_defaults"]["silo-A"]
    assert stored["destination"] == str(custom)
    dlg.deleteLater()

    dlg2, _cap2 = _dlg(loaded)
    assert str(custom) in [dlg2.cmb_dest.itemData(i)
                           for i in range(dlg2.cmb_dest.count())]
    dlg2.deleteLater()


# --- F: the chosen options reach the archive ------------------------------

def _pack(loaded, dlg):
    options = dlg._options()
    op = loaded._silo_bundle_request(capture=dlg.capture, options=options)
    deadline = 20.0
    import time

    # Drive the same event loop the app drives.
    from PyQt6.QtWidgets import QApplication as _A
    end = time.time() + deadline
    while time.time() < end:
        _A.processEvents()
        # The registry empties on `finished`, which is emitted before the
        # worker's own event loop stops; wait for the thread too, or teardown
        # races the QThread destructor.
        if op is not None and not op.thread.isRunning():
            break
        time.sleep(0.01)
    _A.processEvents()
    return options


def test_a_deselected_item_is_absent_from_the_archive(loaded):
    dlg, _cap = _dlg(loaded)
    dlg._set_all(False)
    dlg.list.item(0).setCheckState(Qt.CheckState.Checked)
    _pack(loaded, dlg)
    with zipfile.ZipFile(loaded._last_bundle_path) as zf:
        names = zf.namelist()
    assert any(n.startswith("media/") for n in names)
    assert len([n for n in names if n.startswith("media/")]) == 1
    dlg.deleteLater()


def test_packing_from_the_dialog_never_edits_the_silo_text(loaded):
    before = loaded.text
    dlg, _cap = _dlg(loaded)
    dlg.chk_text.setChecked(False)
    _pack(loaded, dlg)
    assert loaded.text == before
    dlg.deleteLater()


def test_unchecking_the_text_drops_the_markdown_from_the_archive(loaded):
    dlg, _cap = _dlg(loaded)
    dlg.chk_text.setChecked(False)
    _pack(loaded, dlg)
    with zipfile.ZipFile(loaded._last_bundle_path) as zf:
        assert "My Silo.md" not in zf.namelist()
    dlg.deleteLater()


def test_keep_original_links_leaves_the_absolute_path_in_the_markdown(loaded):
    dlg, _cap = _dlg(loaded)
    dlg.cmb_port.setCurrentIndex(dlg.cmb_port.findData(False))
    _pack(loaded, dlg)
    with zipfile.ZipFile(loaded._last_bundle_path) as zf:
        body = zf.read("My Silo.md").decode("utf-8")
    assert "file:///" in body
    dlg.deleteLater()


# --- H: what is remembered -----------------------------------------------

def test_the_per_file_selection_is_never_persisted(loaded):
    dlg, _cap = _dlg(loaded)
    dlg._set_all(False)
    dlg.chk_remember.setChecked(True)
    dlg.accept()
    stored = loaded.data["silo_bundle_defaults"]["silo-A"]
    assert "selected" not in stored
    assert "excluded" not in stored
    dlg.deleteLater()

    dlg2, _cap2 = _dlg(loaded)
    assert dlg2._selected_sources()       # a fresh, honest view of the silo
    assert len(dlg2._selected_sources()) == 3
    dlg2.deleteLater()


def test_remembered_choices_are_reapplied_on_the_next_open(loaded):
    dlg, _cap = _dlg(loaded)
    dlg.chk_attach.setChecked(True)
    dlg.cmb_port.setCurrentIndex(dlg.cmb_port.findData(False))
    dlg.chk_remember.setChecked(True)
    dlg.accept()
    dlg.deleteLater()

    dlg2, _cap2 = _dlg(loaded)
    assert dlg2.chk_attach.isChecked()
    assert dlg2.cmb_port.currentData() is False
    assert dlg2.chk_remember.isChecked()
    dlg2.deleteLater()


def test_a_silo_with_no_media_still_offers_the_text(win):
    # The bare `win` fixture: an empty silo folder and words only, so the
    # Silo-Files sweep has nothing to find either.
    win.text = "# Notes only\n\nnothing but words\n"
    dlg, _cap = _dlg(win)
    assert dlg.list.count() == 0
    assert dlg.btn_pack.isEnabled()
    assert dlg.chk_text.isChecked()
    dlg.deleteLater()
