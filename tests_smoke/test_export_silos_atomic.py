"""T-813 regression: BackupDialog.export_silos must be non-destructive and
atomic.

Three guarantees:
1. Pre-existing destination files are never truncated without explicit
   overwrite consent — declining the prompt must leave every byte untouched.
2. A failure mid-export never leaves truncated targets: each file is written
   to a temp sibling and published with os.replace only once COMPLETE, so the
   old bytes survive a failed write and orphan temps are cleaned up.
3. A clean export still produces every non-empty silo, temp and archive.

Uses a lightweight stub window (a bare QWidget), NOT the full FastPrompter
window, so it runs anywhere Qt can start offscreen.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from fastprompter.ui.backup_dialog import BackupDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class StubWin(QWidget):
    def __init__(self):
        super().__init__()
        self._current_lang = "EN"
        self.data = {
            "cats_order": ["alpha", "beta"],
            "temp_presets_all": {
                "alpha": ["first text", "", "third text"],
                "beta": ["beta one"],
            },
            "archive_temp_presets_all": {
                "alpha": ["archived one"],
            },
        }
        self.state = type("S", (), {"_sanitize_cat_name": staticmethod(
            lambda s: s.replace(" ", "_").replace("/", "_"))})()

    def save_data_to_db(self, force=False):
        return True


def _dialog(tmp_path, qapp, monkeypatch, ask_response=None):
    win = StubWin()
    dlg = BackupDialog(win)
    monkeypatch.setattr(
        "fastprompter.ui.backup_dialog.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path))
    calls = []

    def fake_question(*a, **k):
        calls.append(("question", a, k))
        return ask_response if ask_response is not None \
            else QMessageBox.StandardButton.No

    def fake_info(*a, **k):
        calls.append(("info", a, k))

    def fake_critical(*a, **k):
        calls.append(("critical", a, k))

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(fake_info))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(fake_critical))
    return dlg, win, calls


def _files(tmp_path):
    out = {}
    for root, _dirs, names in os.walk(tmp_path):
        for n in names:
            p = os.path.join(root, n)
            with open(p, encoding="utf-8") as fh:
                out[os.path.relpath(p, tmp_path)] = fh.read()
    return out


def test_clean_export_writes_every_silo(tmp_path, qapp, monkeypatch):
    dlg, _win, calls = _dialog(tmp_path, qapp, monkeypatch)
    dlg.combo_format.setCurrentText(".txt")
    dlg.export_silos()
    got = _files(tmp_path)
    assert got == {
        os.path.join("alpha", "Silo_1.txt"): "first text",
        os.path.join("alpha", "Silo_3.txt"): "third text",
        os.path.join("alpha", "Archive_Silo_1.txt"): "archived one",
        os.path.join("beta", "Silo_1.txt"): "beta one",
    }
    assert all(n.endswith("_1.txt") or n.endswith("_3.txt")
               or "Archive" in n for n in got)
    assert not [n for n in got if ".tmp" in n], "orphan temp left behind"
    assert not [c for c in calls if c[0] == "question"], "no collision, no prompt"
    assert any(c[0] == "info" and "Silos exported" in c[1][2] for c in calls)
    assert not [c for c in calls if c[0] == "critical"]


def test_collision_without_consent_preserves_originals(tmp_path, qapp, monkeypatch):
    target = os.path.join("alpha", "Silo_1.txt")
    os.makedirs(os.path.join(tmp_path, "alpha"), exist_ok=True)
    with open(os.path.join(tmp_path, target), "w", encoding="utf-8") as fh:
        fh.write("ORIGINAL")
    dlg, _win, calls = _dialog(tmp_path, qapp, monkeypatch, ask_response=None)
    dlg.combo_format.setCurrentText(".txt")
    dlg.export_silos()
    got = _files(tmp_path)
    assert got[target] == "ORIGINAL", "existing file must survive without consent"
    assert len(got) == 1, "no other file may be written when consent is refused"
    assert any(c[0] == "question" for c in calls), "user must be asked"
    assert any(c[0] == "info" and "No files were changed" in c[1][2] for c in calls)
    assert not [c for c in calls if c[0] == "critical"]


def test_collision_with_consent_overwrites(tmp_path, qapp, monkeypatch):
    target = os.path.join("alpha", "Silo_1.txt")
    os.makedirs(os.path.join(tmp_path, "alpha"), exist_ok=True)
    with open(os.path.join(tmp_path, target), "w", encoding="utf-8") as fh:
        fh.write("ORIGINAL")
    dlg, _win, calls = _dialog(
        tmp_path, qapp, monkeypatch,
        ask_response=QMessageBox.StandardButton.Yes)
    dlg.combo_format.setCurrentText(".txt")
    dlg.export_silos()
    got = _files(tmp_path)
    assert got[target] == "first text"
    assert len(got) == 4, "consented export writes the full plan"


def test_mid_export_failure_leaves_no_truncated_targets(tmp_path, qapp, monkeypatch):
    for target in ("Silo_1.txt", "Silo_3.txt"):
        os.makedirs(os.path.join(tmp_path, "alpha"), exist_ok=True)
        with open(os.path.join(tmp_path, "alpha", target), "w",
                  encoding="utf-8") as fh:
            fh.write("ORIGINAL-" + target)

    import fastprompter.ui.backup_dialog as mod

    real_replace = os.replace

    def failing_replace(src, dst):
        if dst.endswith("Silo_3.txt"):
            raise OSError("injected failure")
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", failing_replace)
    dlg, _win, calls = _dialog(
        tmp_path, qapp, monkeypatch,
        ask_response=QMessageBox.StandardButton.Yes)
    dlg.combo_format.setCurrentText(".txt")
    dlg.export_silos()

    got = _files(tmp_path)
    assert got[os.path.join("alpha", "Silo_1.txt")] == "first text", \
        "complete replace before the failure is fine"
    assert got[os.path.join("alpha", "Silo_3.txt")] == "ORIGINAL-Silo_3.txt", \
        "failed publish must leave the original bytes intact"
    assert not [n for n in got if ".tmp" in n], "orphan temp must be cleaned up"
    assert "Archive_Silo_1.txt" not in got, \
        "files after the failure point must not be published"
    assert "beta" not in got
    assert any(c[0] == "critical" and "Failed to export" in c[1][2]
               for c in calls), "failure must be reported"
    assert not any("Silo_1" in n for n in got if "tmp" in n)


def test_nothing_to_export_is_reported(tmp_path, qapp, monkeypatch):
    win = StubWin()
    win.data["temp_presets_all"] = {}
    win.data["archive_temp_presets_all"] = {}
    dlg = BackupDialog(win)
    monkeypatch.setattr(
        "fastprompter.ui.backup_dialog.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path))
    calls = []

    def fake_info(*a, **k):
        calls.append(("info", a, k))

    monkeypatch.setattr(QMessageBox, "information", staticmethod(fake_info))
    dlg.combo_format.setCurrentText(".txt")
    dlg.export_silos()
    assert _files(tmp_path) == {}
    assert any("Nothing to export" in c[1][2] for c in calls)
