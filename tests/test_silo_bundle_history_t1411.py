"""T-1411 - smart silo bundle history.

The window harness is the SAME shipped-methods-on-a-QWidget double T-1409
uses (imported, not re-implemented).

Foundational contracts (written RED against T-1410 first):
A  an unchanged repeat Plain Quick Pack creates NO second ZIP and copies the
   first archive again
B  a header with ':' yields a readable archive name, never ``silo_bundle_``
C  Copy Last Bundle is per-silo: silo B never receives silo A's archive
D  remembered Shift-dialog choices actually drive the next Plain Quick Pack
"""
import json
import os
import zipfile

from PyQt6.QtWidgets import QApplication
from test_silo_bundle_clipboard_t1409 import (  # noqa: F401
    _body,
    _clipboard_urls,
    _members,
    _png,
    _run,
    _Win,
)
from test_silo_bundle_clipboard_t1409 import win as _win_fixture

win = _win_fixture


def _zips(folder):
    folder = str(folder)
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, n) for n in os.listdir(folder)
                  if n.lower().endswith(".zip"))


def _exports(win):
    return os.path.join(win.silo_dir, "exports")


# --- A: content-identical reuse -------------------------------------------

def test_a_unchanged_repeat_quick_pack_reuses_the_first_archive(win):
    shot = _png(win.silo_dir, "shot.png")
    win.text = _body(shot)

    _run(win)
    first = _zips(_exports(win))
    assert len(first) == 1, first

    QApplication.clipboard().clear()
    _run(win)

    assert _zips(_exports(win)) == first, "an unchanged pack must not repack"
    assert _clipboard_urls() == [os.path.normpath(first[0])]
    assert win.toasts[-1][0] == "Bundle unchanged"


# --- B: header-derived readable names -------------------------------------

def test_b_header_with_colon_names_the_archive_readably(win):
    win.text = "# FastPrompter: (Evening 03 Oct - 17:39)\n\nbody\n"

    _run(win)

    zips = _zips(_exports(win))
    assert len(zips) == 1, zips
    name = os.path.basename(zips[0])
    assert not name.startswith("silo_bundle"), name
    assert name.startswith("FastPrompter - (Evening 03 Oct - 17-39)_bundle_"), name
    members = _members(zips[0])
    assert "FastPrompter - (Evening 03 Oct - 17-39).md" in members, members
    with zipfile.ZipFile(zips[0]) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["silo_title"] == "FastPrompter: (Evening 03 Oct - 17:39)"


# --- C: last bundle is per silo -------------------------------------------

def test_c_copy_last_never_hands_silo_a_archive_to_silo_b(win, tmp_path):
    _run(win)
    a_zip = _zips(_exports(win))[0]

    other = tmp_path / "silo-b"
    other.mkdir()
    win.silo_dir = str(other)
    win._active_silo_id = lambda: "silo-B"
    QApplication.clipboard().clear()

    win._silo_bundle_copy_last()

    assert os.path.normpath(a_zip) not in _clipboard_urls()
    assert win.toasts[-1][0] == "No previous bundle"


# --- D: remembered defaults drive Quick Pack -------------------------------

def test_d_remembered_choices_drive_the_next_plain_quick_pack(win):
    _png(win.silo_dir, "shot.png")
    with open(os.path.join(win.silo_dir, "notes.txt"), "w") as fh:
        fh.write("attachment")
    win._silo_bundle_remember_defaults("silo-A", {
        "include_text": False, "include_attachments": True,
        "hide_local_paths": True, "remember": True, "destination": "",
    })

    _run(win)

    zips = _zips(_exports(win))
    assert len(zips) == 1, zips
    members = _members(zips[0])
    assert "My Silo.md" not in members, members
    assert any(m.startswith("attachments/") and m.endswith("notes.txt")
               for m in members), members


# --- E: content revert reuses older candidate -----------------------------

def test_e_content_revert_to_older_candidate_reuses_it(win):
    win.text = "# Silo Title\n\nVersion 1\n"
    _run(win)
    zips_1 = _zips(_exports(win))
    assert len(zips_1) == 1
    zip1 = zips_1[0]

    win.text = "# Silo Title\n\nVersion 2\n"
    _run(win, {"force_repack": True})
    zips_2 = _zips(_exports(win))
    assert len(zips_2) == 2
    assert zip1 in zips_2

    # Revert back to Version 1 content
    win.text = "# Silo Title\n\nVersion 1\n"
    QApplication.clipboard().clear()
    _run(win)

    # Reused zip1, no third archive created!
    zips_3 = _zips(_exports(win))
    assert len(zips_3) == 2
    assert _clipboard_urls() == [os.path.normpath(zip1)]
    assert win.toasts[-1][0] == "Bundle unchanged"


# --- F: force repack always builds a fresh archive ------------------------

def test_f_force_repack_creates_new_archive_despite_identical_content(win):
    _run(win)
    first_zips = _zips(_exports(win))
    assert len(first_zips) == 1

    _run(win, {"force_repack": True})
    second_zips = _zips(_exports(win))
    assert len(second_zips) == 2
    assert win.toasts[-1][0] == "Silo packed"


# --- G: open last bundle folder -------------------------------------------

def test_g_alt_click_open_last_bundle_folder(win, tmp_path):
    revealed = []
    win._reveal_path = lambda path: revealed.append(path)

    # Before packing: fallback to exports dir
    win._silo_bundle_open_last_folder()
    assert len(revealed) == 1
    assert revealed[-1] == _exports(win)

    # Pack to a custom folder
    custom_dir = str(tmp_path / "custom_exports")
    os.makedirs(custom_dir, exist_ok=True)
    _run(win, {"target_dir": custom_dir})

    win._silo_bundle_open_last_folder()
    assert len(revealed) == 2
    assert revealed[-1] == custom_dir


# --- H: retention prunes to keep_versions ---------------------------------

def test_h_retention_default_five_pruning(win):
    # Create 7 distinct archives using force_repack
    for idx in range(7):
        win.text = f"# Silo Title\n\nUpdate {idx}\n"
        _run(win, {"force_repack": True})

    zips = _zips(_exports(win))
    assert len(zips) == 5, f"Expected 5 retained archives, found {len(zips)}"

    hist = win._silo_bundle_history(win._active_silo_id())
    assert len(hist["records"]) == 5


# --- I: retention keep_versions = 1 ---------------------------------------

def test_i_retention_keep_one_leaving_exact_newest(win):
    win.data["silo_bundle_keep_versions"] = "1"
    win.text = "# Silo Title\n\nVersion A\n"
    _run(win)
    assert len(_zips(_exports(win))) == 1

    win.text = "# Silo Title\n\nVersion B\n"
    _run(win, {"force_repack": True})
    zips = _zips(_exports(win))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        body = zf.read("Silo Title.md").decode("utf-8")
    assert "Version B" in body


# --- J: failed pack preserves old version ---------------------------------

def test_j_failed_pack_preserves_old_version(win):
    win.text = "# Silo Title\n\nExisting\n"
    _run(win)
    zips_before = _zips(_exports(win))
    assert len(zips_before) == 1

    # Empty pack request (unchecked text and no attachments)
    _run(win, {"include_text": False, "excluded": []})
    assert len(_zips(_exports(win))) == 1
    assert _zips(_exports(win)) == zips_before
    assert win.toasts[-1][0] == "Nothing to pack"


# --- K: custom destination not auto-pruned --------------------------------

def test_k_custom_destination_not_auto_pruned_by_default(win, tmp_path):
    custom_dir = str(tmp_path / "custom_out")
    os.makedirs(custom_dir, exist_ok=True)
    win.data["silo_bundle_keep_versions"] = "2"

    for idx in range(4):
        win.text = f"# Silo Title\n\nCustom {idx}\n"
        _run(win, {"target_dir": custom_dir, "force_repack": True})

    custom_zips = _zips(custom_dir)
    assert len(custom_zips) == 4, "Custom destination must not be auto-pruned"


# --- L: history survives reload / restart ---------------------------------

def test_l_history_survives_restart(win, tmp_path, qapp):
    win.text = "# Silo Title\n\nPersistent\n"
    _run(win)
    zips = _zips(_exports(win))
    assert len(zips) == 1
    zip_path = zips[0]

    # Simulate restart by instantiating new _Win with win.data
    w2 = _Win()
    w2.data = dict(win.data)
    w2.text = win.text
    w2.active_temp_slot = win.active_temp_slot
    w2.active_is_archive = win.active_is_archive
    w2.editing_snippet = False
    w2._current_lang = "EN"
    w2.silo_dir = win.silo_dir
    w2.toasts = []
    w2._last_bundle_path = None
    w2._bundle_ops = {}
    w2._bundle_version_cache = ""
    w2._editor_text_snapshot = lambda: w2.text
    w2._silo_folder_dir = lambda slot, is_archive=False: w2.silo_dir
    w2._silo_document_bound = lambda slot, is_archive: True
    w2._active_silo_id = lambda: "silo-A"
    w2.get_current_category = lambda: "Notes"
    w2.save_data_to_db = lambda *a, **k: True
    w2._show_in_app_toast = (
        lambda title, message, **kw: w2.toasts.append((title, message, kw)))

    QApplication.clipboard().clear()
    w2._silo_bundle_copy_last()
    assert _clipboard_urls() == [os.path.normpath(zip_path)]
    assert w2.toasts[-1][0] == "Last bundle copied"
    w2.close()
    w2.deleteLater()


# --- M: editor modifier dispatch mode ------------------------------------

def test_m_editor_modifier_dispatch_mode(win):
    from types import SimpleNamespace

    from fastprompter.ui.editor import VaultTextEdit

    dispatched = []
    stub = SimpleNamespace(
        _silo_bundle_copy_last=lambda: dispatched.append("copy_last"),
        _silo_bundle_open_last_folder=lambda: dispatched.append("open_last_folder"),
        silo_bundle_force_repack=lambda: dispatched.append("force_repack"),
        silo_bundle_with_options=lambda: dispatched.append("with_options"),
        silo_bundle_quick_pack=lambda: dispatched.append("quick_pack"),
    )
    editor_stub = SimpleNamespace(main_win=stub)
    # Call VaultTextEdit._silo_bundle_dispatch_mode directly
    VaultTextEdit._silo_bundle_dispatch_mode(editor_stub, "copy_last")
    VaultTextEdit._silo_bundle_dispatch_mode(editor_stub, "open_last_folder")
    VaultTextEdit._silo_bundle_dispatch_mode(editor_stub, "force_repack")
    VaultTextEdit._silo_bundle_dispatch_mode(editor_stub, "with_options")
    VaultTextEdit._silo_bundle_dispatch_mode(editor_stub, "quick_pack")

    assert dispatched == [
        "copy_last",
        "open_last_folder",
        "force_repack",
        "with_options",
        "quick_pack",
    ]

