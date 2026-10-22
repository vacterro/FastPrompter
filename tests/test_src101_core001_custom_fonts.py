"""SRC-101 CORE-001 (audit/18): a loaded custom font must survive a restart.

``load_custom_font`` called ``QFontDatabase.addApplicationFont(path)`` and
persisted ONLY the returned runtime ``font_id`` in ``data["custom_font_ids"]``.
An id is a handle into the font database of ONE process: after a restart
nothing registered the file again, so the custom family vanished while
``font_family`` still named it -- persisted state, the combo-box selection and
real Qt resolution disagreed, deterministically, for every custom font.

The repair persists the font's SOURCE PATH (``custom_font_paths``: a JSON list
whose members must be strings), keeps the Qt ids instance-only in
``_custom_font_runtime_ids``, and re-registers every persisted path before the
saved ``font_family`` is looked up.
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QMessageBox,
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import fastprompter.core.state as state_mod  # noqa: E402
from fastprompter.ui.theme_mixin import (  # noqa: E402
    _BUILTIN_FONTS,
    ThemeMixin,
)

_APP = QApplication.instance() or QApplication([])

# Families present on a stock Windows install that are NOT in the shipped
# selector, so "it is in the combo" cannot be satisfied by a built-in.
_CANDIDATE_FONTS = (
    "comic.ttf", "framd.ttf", "BOOKOS.TTF", "trebuc.ttf",
    "impact.ttf", "georgia.ttf",
)


def _combos_items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


@pytest.fixture(scope="module")
def custom_font():
    """(path, family) for a real TTF, copied OUT of the system font dir.

    Outside the system directory on purpose: Qt can only know this font because
    something called ``addApplicationFont`` for it, which is what makes the
    restart assertion mean something.
    """
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    tmp = tempfile.mkdtemp(prefix="src101_core001_")
    for name in _CANDIDATE_FONTS:
        src = os.path.join(fonts_dir, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(tmp, name)
        try:
            with open(src, "rb") as fin, open(dst, "wb") as fout:
                fout.write(fin.read())
        except OSError:
            continue
        font_id = QFontDatabase.addApplicationFont(dst)
        if font_id < 0:
            continue
        families = list(QFontDatabase.applicationFontFamilies(font_id))
        QFontDatabase.removeApplicationFont(font_id)
        outside = [f for f in families if f not in _BUILTIN_FONTS]
        if outside:
            return dst, outside[0]
    pytest.skip("no usable non-builtin TTF on this machine")


class _Host(ThemeMixin):
    """ThemeMixin over exactly the surface the font methods touch."""

    def __init__(self, data, family=None):
        self.data = data
        self.font_combo = QComboBox()
        self.font_combo.addItems(list(_BUILTIN_FONTS))
        self.ignore_focus_loss = False
        self._current_lang = "EN"
        self._font_family = family or data.get("font_family", "Verdana")
        self.dirty = []
        self._custom_font_runtime_ids = []

    def mark_dirty(self, domain=None):
        self.dirty.append(domain)

    def change_font_family(self, name):
        self._font_family = name
        self.data["font_family"] = name
        self.mark_dirty("settings")

    def activateWindow(self):
        pass


def _silence_dialogs(monkeypatch, path=None):
    if path is not None:
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: None))


class TestLoadingPersistsTheSourceNotTheId:
    def test_the_absolute_source_path_is_what_gets_persisted(
            self, custom_font, monkeypatch, tmp_path):
        path, family = custom_font
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        # A relative selection must still persist absolutely: the durable value
        # has to resolve after the process restarts somewhere else.
        relative = os.path.relpath(path, workdir)
        _silence_dialogs(monkeypatch, relative)

        host = _Host({})
        host.load_custom_font()

        assert host.data["custom_font_paths"] == [os.path.abspath(path)]
        assert "custom_font_ids" not in host.data
        # runtime-only, never persisted state
        assert host._custom_font_runtime_ids
        assert host.dirty == ["settings"]
        assert family in _combos_items(host.font_combo)
        assert host.font_combo.currentText() == family
        host._unregister_custom_fonts()

    def test_a_second_load_of_the_same_file_does_not_duplicate(
            self, custom_font, monkeypatch):
        path, family = custom_font
        _silence_dialogs(monkeypatch, path)
        host = _Host({})
        host.load_custom_font()
        host.load_custom_font()
        assert host.data["custom_font_paths"] == [os.path.abspath(path)]
        assert _combos_items(host.font_combo).count(family) == 1
        host._unregister_custom_fonts()


class TestRestoreRebuildsFromPathsAlone:
    def test_a_fresh_host_registers_the_persisted_path(self, custom_font):
        path, family = custom_font
        host = _Host({"custom_font_paths": [path], "font_family": family})
        assert family not in _combos_items(host.font_combo)

        families = host.restore_custom_fonts()

        assert families == [family]
        assert family in _combos_items(host.font_combo)
        assert host._custom_font_runtime_ids
        for font_id in host._custom_font_runtime_ids:
            assert family in QFontDatabase.applicationFontFamilies(font_id)
        host._unregister_custom_fonts()

    def test_nothing_runtime_is_ever_persisted(self, custom_font):
        path, family = custom_font
        host = _Host({"custom_font_paths": [path]})
        host.restore_custom_fonts()
        assert "custom_font_ids" not in host.data
        assert all(isinstance(p, str) for p in host.data["custom_font_paths"])
        host._unregister_custom_fonts()

    def test_restore_is_idempotent(self, custom_font):
        path, family = custom_font
        host = _Host({"custom_font_paths": [path]})
        host.restore_custom_fonts()
        first = _combos_items(host.font_combo)
        host.restore_custom_fonts()
        assert _combos_items(host.font_combo) == first
        assert _combos_items(host.font_combo).count(family) == 1
        host._unregister_custom_fonts()

    def test_a_legacy_str_blob_registers_nothing_and_does_not_crash(self):
        host = _Host({"custom_font_paths": "[1, 2, 3]"})
        assert host.restore_custom_fonts() == []
        assert _combos_items(host.font_combo) == list(_BUILTIN_FONTS)

    def test_a_wrong_type_row_does_not_crash(self):
        host = _Host({"custom_font_paths": {"nope": True}})
        assert host.restore_custom_fonts() == []
        assert _combos_items(host.font_combo) == list(_BUILTIN_FONTS)

    def test_a_missing_file_leaves_no_phantom_selector_entry(self, tmp_path):
        missing = str(tmp_path / "gone.ttf")
        host = _Host({"custom_font_paths": [missing],
                      "font_family": "GoneFamily"})
        assert host.restore_custom_fonts() == []
        items = _combos_items(host.font_combo)
        assert items == list(_BUILTIN_FONTS)
        assert host.font_combo.findText("GoneFamily") < 0
        # The user's intent survives a font that is merely unreachable right
        # now (an unmounted drive) -- it is not silently deleted.
        assert host.data["custom_font_paths"] == [missing]


class TestClearReleasesBothHalves:
    def test_clear_drops_the_sources_and_the_runtime_registration(
            self, custom_font, monkeypatch):
        path, family = custom_font
        host = _Host({"custom_font_paths": [path], "font_family": family})
        host._font_family = family
        host.restore_custom_fonts()
        assert host._custom_font_runtime_ids
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

        host.clear_custom_fonts()

        assert host.data["custom_font_paths"] == []
        assert host._custom_font_runtime_ids == []
        assert _combos_items(host.font_combo) == list(_BUILTIN_FONTS)
        assert host.data["font_family"] == "Verdana"
        assert "settings" in host.dirty


class TestProfilesDoNotInherit:
    def test_a_profile_without_custom_fonts_shows_none(self, custom_font):
        path, family = custom_font
        host = _Host({"custom_font_paths": [path], "font_family": family})
        host.restore_custom_fonts()
        assert family in _combos_items(host.font_combo)

        # profile switch: self.data is replaced by the new profile's settings
        host.data = {"custom_font_paths": [], "font_family": "Verdana"}
        host._font_family = "Verdana"
        host.restore_custom_fonts()

        assert _combos_items(host.font_combo) == list(_BUILTIN_FONTS)
        assert host._custom_font_runtime_ids == []


class TestTheRealWindowRestoresBeforeSelecting:
    """The production startup path: restore must precede the saved-font lookup.

    Two real windows over ONE database: the first loads a font and saves, the
    second is constructed against that database exactly as a restart would.
    """

    def test_a_custom_font_survives_a_window_restart(
            self, custom_font, monkeypatch, tmp_path_factory):
        path, family = custom_font
        db = tmp_path_factory.mktemp("src101_core001_db") / "core001.db"

        original_get_db_path = state_mod.get_db_path
        state_mod.get_db_path = lambda profile_id=1: str(db)
        import fastprompter.utils.portable_backup as backup_mod
        original_backup = backup_mod.run_portable_backup
        backup_mod.run_portable_backup = lambda data, profile_id=1, **_kw: None

        from fastprompter.main import FastPrompter
        originals = {
            name: getattr(FastPrompter, name)
            for name in ("setup_single_instance_server",
                         "register_all_hotkeys", "unregister_all_hotkeys")
        }
        FastPrompter.setup_single_instance_server = lambda self: None
        FastPrompter.register_all_hotkeys = lambda self: None
        FastPrompter.unregister_all_hotkeys = lambda self: None
        _silence_dialogs(monkeypatch, path)

        windows = []
        retired = set()

        def build():
            w = FastPrompter()
            for _ in range(5):
                _APP.processEvents()
            w._initializing_ui = False
            w._suspend_temp_sync = False
            windows.append(w)
            return w

        def retire_window(w):
            if id(w) in retired:
                return
            retired.add(id(w))
            for name in ("auto_save_timer", "topmost_timer", "_cache_timer"):
                timer = getattr(w, name, None)
                if timer is not None:
                    timer.stop()
            service = getattr(w, "limit_service", None)
            if service is not None:
                service.shutdown()
            # what a process exit does to the runtime registration
            w._unregister_custom_fonts()
            if getattr(w, "state", None) is not None:
                w.state.conn = None
            w.close()

        try:
            first = build()
            first.load_custom_font()
            assert first.data["custom_font_paths"] == [os.path.abspath(path)]
            assert "custom_font_ids" not in first.data
            assert family in _combos_items(first.font_combo)
            assert first.state.save_data_to_db("", force=True) is True
            retire_window(first)

            second = build()
            items = _combos_items(second.font_combo)
            assert family in items, "the custom family was not restored"
            assert second.font_combo.currentText() == family
            assert second._custom_font_runtime_ids
            for font_id in second._custom_font_runtime_ids:
                assert family in QFontDatabase.applicationFontFamilies(font_id)
        finally:
            for w in windows:
                retire_window(w)
            for name, value in originals.items():
                setattr(FastPrompter, name, value)
            state_mod.get_db_path = original_get_db_path
            backup_mod.run_portable_backup = original_backup
