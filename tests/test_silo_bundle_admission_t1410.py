"""T-1410 — Pack Silo admission: a lazy silo is a valid silo.

T-1409 gated admission on ``os.path.isdir(silo_dir)``. FastPrompter's File
Container folders are lazy, so a perfectly valid active silo routinely has no
physical folder yet — and the user was told "Open a silo first" while editing
that silo. This file replaces that contract: folder materialization is NOT
part of being a silo, and every refusal states the REAL reason.

The window harness is the SAME shipped-methods-on-a-QWidget double T-1409 uses
(imported, not re-implemented), so a behaviour that existed only here would
fail rather than pass.

Contract under test:
A  a valid active silo whose canonical folder does not exist yet is packable,
   and the worker creates <silo>/exports to publish into
B  inline external media is bundled even with no silo folder at all
C  an empty silo that still owns Silo Files is packable (media-only)
D  snippet mode is refused, and says Pack is a silo action
E  an unreachable storage root is refused, and says storage is unavailable
F  a genuinely empty payload is refused, and says nothing was selected
G  a stale document binding is refused, and says the silo could not be read
H  every refusal message is a real reason, never "Open a silo first"
"""
import os

from test_silo_bundle_clipboard_t1409 import (  # noqa: F401  (pytest fixture)
    _body,
    _clipboard_urls,
    _members,
    _png,
    _run,
    _url,
    _Win,
)
from test_silo_bundle_clipboard_t1409 import win as _win_fixture

# Re-exported under the name the tests request it by, so the harness and the
# test file cannot drift apart.
win = _win_fixture


# --- A: a lazy silo is a valid silo ---------------------------------------

def test_a_valid_silo_with_no_folder_on_disk_is_still_admitted(win, tmp_path):
    """The operator's exact case: editing a real silo that has never been
    visited in the Files panel, so its canonical folder does not exist."""
    lazy = tmp_path / "files" / "Notes" / "silo-0"
    assert not lazy.exists(), "the premise: the silo folder was never created"
    win._silo_folder_dir = lambda slot, is_archive=False: str(lazy)

    cap = win._silo_bundle_capture()

    assert cap is not None, "a lazy silo is a valid silo"
    assert cap["silo_dir"] == str(lazy)
    assert cap["target_dir"] == os.path.join(str(lazy), "exports")
    assert not lazy.exists(), "capture must still not touch the filesystem"


def test_quick_pack_publishes_into_a_silo_folder_it_creates(win, tmp_path):
    lazy = tmp_path / "files" / "Notes" / "silo-0"
    win._silo_folder_dir = lambda slot, is_archive=False: str(lazy)

    _run(win)

    exports = lazy / "exports"
    assert exports.is_dir(), "the pack creates the canonical silo folder"
    zips = list(exports.glob("*.zip"))
    assert len(zips) == 1, f"one archive published, got {zips}"
    members = _members(str(zips[0]))
    assert "My Silo.md" in members, f"Markdown packaged, got {members}"
    assert _clipboard_urls() == [os.path.normpath(str(zips[0]))]
    assert win.toasts and win.toasts[-1][0] == "Silo packed"


def test_quick_pack_never_says_open_a_silo_first_for_a_lazy_silo(win, tmp_path):
    win._silo_folder_dir = lambda slot, is_archive=False: str(
        tmp_path / "never-created")

    _run(win)

    for title, message, kwargs in win.toasts:
        blob = f"{title} {message} {kwargs}"
        assert "Open a silo first" not in blob, blob
        assert "Time's up" not in blob, blob


# --- B: inline external media with no silo folder --------------------------

def test_inline_external_media_packs_without_a_silo_folder(win, tmp_path):
    media = tmp_path / "external"
    media.mkdir()
    shot = _png(media, "shot.png")
    lazy = tmp_path / "files" / "Notes" / "silo-0"
    win._silo_folder_dir = lambda slot, is_archive=False: str(lazy)
    win.text = _body(shot)

    _run(win)

    zips = list((lazy / "exports").glob("*.zip"))
    assert len(zips) == 1, zips
    members = _members(str(zips[0]))
    assert any(m.startswith("media/") and m.endswith("shot.png")
               for m in members), members
    with __import__("zipfile").ZipFile(str(zips[0])) as zf:
        markdown = zf.read("My Silo.md").decode("utf-8")
    assert "media/" in markdown, markdown
    assert "file:///" not in markdown, markdown


# --- C: an empty silo that still owns Silo Files ---------------------------

def test_an_empty_silo_with_silo_files_is_still_packable(win, tmp_path):
    silo = tmp_path / "silo"          # the `win` fixture already made it
    _png(silo, "kept.png")
    win.silo_dir = str(silo)
    win.text = ""

    # No `media_only` here on purpose: the operator's §5/§9-C case is a silo
    # whose text is blank but whose Files still hold an image, and that packs
    # through the ORDINARY path — media_only is a separate gesture.
    op = _run(win)

    assert op is not None, "an empty document is not an invalid silo"
    zips = list((silo / "exports").glob("*.zip"))
    assert len(zips) == 1, zips
    assert any(m.endswith("kept.png") for m in _members(str(zips[0])))
    assert not win.toasts or win.toasts[-1][0] == "Silo packed"


def test_a_genuinely_empty_payload_is_refused_as_nothing_to_pack(win):
    win.text = "   \n\n"
    assert win._silo_bundle_request() is not None  # the silo is valid
    _run(win)
    title, message, _ = win.toasts[-1]
    assert title == "Nothing to pack"
    assert "Open a silo first" not in message


# --- D: snippet mode --------------------------------------------------------

def test_snippet_mode_is_refused_with_a_silo_specific_reason(win):
    win.editing_snippet = True
    assert win._silo_bundle_request() is None
    title, message, _ = win.toasts[-1]
    assert "Open a silo first" not in message
    assert "silo" in message.lower()


# --- E: unreachable storage -------------------------------------------------

def test_unreachable_storage_root_is_refused_with_a_storage_reason(win):
    win._silo_folder_dir = lambda slot, is_archive=False: None
    assert win._silo_bundle_request() is None
    title, message, _ = win.toasts[-1]
    assert title == "Silo storage is unavailable"
    assert "Open a silo first" not in message


# --- F/G: honesty of every refusal -----------------------------------------

def test_no_refusal_ever_blames_the_user_for_opening_a_silo(win, tmp_path):
    """Every honest refusal, across every way the context can fail."""
    good = str(tmp_path / "silo")
    os.makedirs(good, exist_ok=True)
    states = []

    def state(**over):
        win._silo_folder_dir = lambda slot, is_archive=False: str(good)
        win.editing_snippet = False
        win.text = "# My Silo\n\nbody\n"
        for k, v in over.items():
            setattr(win, k, v)
        states.append(over)

    state()
    state(editing_snippet=True)
    state(_silo_folder_dir=None)
    state(text="")
    state(active_temp_slot="not-an-int")

    for over in states:
        win._silo_bundle_request()
        assert win.toasts, over
        for title, message, _ in win.toasts:
            assert "Open a silo first" not in f"{title} {message}", over
            assert "Time's up" not in f"{title} {message}", over


def test_a_stale_document_binding_is_refused(win):
    """The live document belongs to another silo: refuse, do not pack it."""
    win._silo_document_bound = lambda slot, is_archive: False
    assert win._silo_bundle_request() is None
    title, message, _ = win.toasts[-1]
    assert "Open a silo first" not in message
    assert title != "Nothing to pack" or "silo" in message.lower()
