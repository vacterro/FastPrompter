"""T-1409 — the Shift+click Pack-with-options dialog.

Shift+clicking the header control opens this. It is a COMPACT dialog, not a
settings page: it exists so the user can see what is about to be bundled,
drop what they do not want, and say where it goes — then hand the SAME frozen
capture it previewed back to the one backend that does the packing.

Deliberate simplifications
--------------------------
* Row thumbnails are plain ``QIcon(path)``s. Qt only decodes an icon when it
  is actually painted, so a scrolled-out-of-view image is never decoded, and
  rows appear instantly without a worker pool. If this dialog ever grows to
  hundreds of rows, swap in ``file_container``'s thumb pool here — the row
  builder is the only place that would change.
* Only the media is listed per row; a non-media Silo File (opted into below)
  is a checkbox-less statement of intent, not a second list.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from fastprompter.core.translations import tr

# Source labels shown in the Source column. Kept as data, not tr() keys: they
# are short enum-ish tags, and the dialog's own controls carry the meaning.
_SOURCE_LABELS = {
    "inline": "Inline",
    "silo_files": "Silo Files",
    "both": "Inline + Silo Files",
}

_SORTS = ("newest", "oldest", "document", "name")


def _human_size(num):
    step = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if step < 1024 or unit == "TB":
            return f"{step:.0f} {unit}" if unit == "B" else f"{step:.1f} {unit}"
        step /= 1024.0
    return f"{step:.1f} TB"


def _human_time(epoch, lang):
    if not epoch:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


class BundleOptionsDialog(QDialog):
    """What goes in, and where it lands."""

    def __init__(self, main_win, capture, lang=None):
        super().__init__(main_win)
        self.win = main_win
        self.capture = capture
        self.lang = lang or getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Pack Silo With Options…", self.lang))
        self.setMinimumSize(560, 520)

        from fastprompter.core import silo_bundle as sb
        self.plan = sb.plan_bundle(**dict(capture["plan_kwargs"]))

        self.defaults = getattr(main_win, "_silo_bundle_defaults", lambda *_: {})(
            capture.get("silo_id"))

        root = QVBoxLayout(self)
        root.setSpacing(6)

        # --- the text row comes FIRST, on purpose: it is the one choice that
        # changes what kind of bundle this is, and burying it under a file
        # list is how it gets missed.
        self.chk_text = QCheckBox(tr("Include silo text (.md)", self.lang))
        self.chk_text.setChecked(bool(self.defaults.get("include_text", True)))
        root.addWidget(self.chk_text)

        # --- media rows
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setIconSize(QSize(40, 40))
        self.list.setUniformItemSizes(False)
        self.list.itemChanged.connect(lambda _i: self._refresh_summary())
        root.addWidget(self.list, 1)

        # Rows are filled at the END of __init__, once the summary label and
        # the Pack button exist: populating here would make the first
        # itemChanged fire at controls that do not exist yet.
        self.rows = []          # (row, source path), index-aligned with the list

        # --- selection tools
        tools = QHBoxLayout()
        self.btn_all = QPushButton(tr("Select All", self.lang))
        self.btn_none = QPushButton(tr("Select None", self.lang))
        self.btn_inv = QPushButton(tr("Invert", self.lang))
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_inv.clicked.connect(self._invert)
        tools.addWidget(self.btn_all)
        tools.addWidget(self.btn_none)
        tools.addWidget(self.btn_inv)
        tools.addStretch(1)

        self.cmb_sort = QComboBox()
        for value, label in (
                ("newest", tr("Newest first", self.lang)),
                ("oldest", tr("Oldest first", self.lang)),
                ("document", tr("Document order", self.lang)),
                ("name", tr("Name", self.lang))):
            self.cmb_sort.addItem(label, value)
        self.cmb_sort.currentIndexChanged.connect(lambda _i: self._populate())
        tools.addWidget(self.cmb_sort)
        root.addLayout(tools)

        self.lbl_summary = QLabel()
        root.addWidget(self.lbl_summary)

        # --- destination
        dest = QHBoxLayout()
        dest.addWidget(QLabel(tr("Destination", self.lang)))
        self.cmb_dest = QComboBox()
        self.cmb_dest.addItem(tr("Silo folder", self.lang), "silo")
        self.cmb_dest.addItem(tr("Desktop", self.lang), "desktop")
        self.cmb_dest.addItem(tr("Documents", self.lang), "documents")
        self.custom_dir = self.defaults.get("destination") or ""
        if self.custom_dir and os.path.isdir(self.custom_dir):
            self.cmb_dest.addItem(os.path.basename(self.custom_dir) or
                                  self.custom_dir, self.custom_dir)
        self.btn_choose = QPushButton(tr("Choose folder…", self.lang))
        self.btn_choose.clicked.connect(self._choose_folder)
        self.cmb_dest.currentIndexChanged.connect(self._update_dest_label)
        dest.addWidget(self.cmb_dest, 1)
        dest.addWidget(self.btn_choose)
        root.addLayout(dest)

        self.lbl_dest = QLabel()
        self.lbl_dest.setWordWrap(True)
        root.addWidget(self.lbl_dest)

        # --- portability
        port = QHBoxLayout()
        port.addWidget(QLabel(tr("Make exported Markdown portable", self.lang)))
        self.cmb_port = QComboBox()
        self.cmb_port.addItem(tr("Hide local path", self.lang), True)
        self.cmb_port.addItem(tr("Keep original links", self.lang), False)
        self.cmb_port.setToolTip(tr(
            "Hide local path rewrites every bundled link to its in-archive "
            "name, so the folder can be shared as-is.", self.lang))
        self.cmb_port.setCurrentIndex(
            0 if self.defaults.get("hide_local_paths", True) else 1)
        port.addWidget(self.cmb_port)
        root.addLayout(port)

        self.chk_attach = QCheckBox(
            tr("Include non-media Silo Files", self.lang))
        self.chk_attach.setChecked(
            bool(self.defaults.get("include_attachments", False)))
        root.addWidget(self.chk_attach)

        row_ret = QHBoxLayout()
        row_ret.addWidget(QLabel(tr("Keep last versions in exports", self.lang)))
        self.spn_keep = QSpinBox()
        self.spn_keep.setRange(1, 50)
        profile_keep = 5
        try:
            profile_keep = int(getattr(main_win, "data", {}).get("silo_bundle_keep_versions", 5))
        except (TypeError, ValueError):
            profile_keep = 5
        default_keep = self.defaults.get("keep_versions", profile_keep)
        try:
            self.spn_keep.setValue(int(default_keep))
        except (TypeError, ValueError):
            self.spn_keep.setValue(5)
        row_ret.addWidget(self.spn_keep)
        row_ret.addStretch(1)
        root.addLayout(row_ret)

        self.chk_remember = QCheckBox(
            tr("Remember these choices for Quick Pack", self.lang))
        self.chk_remember.setChecked(
            bool(self.defaults.get("remember", False)))
        root.addWidget(self.chk_remember)

        # --- buttons
        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton(tr("Cancel", self.lang))
        btn_cancel.clicked.connect(self.reject)
        self.btn_pack = QPushButton(tr("Pack Silo", self.lang))
        self.btn_pack.setDefault(True)
        self.btn_pack.clicked.connect(self.accept)
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_pack)
        root.addLayout(row)

        self.chk_text.toggled.connect(lambda _v: self._refresh_summary())
        self._populate()
        self._update_dest_label()
        self._refresh_summary()

    # -- rows ----------------------------------------------------------
    def _populate(self):
        order = self.cmb_sort.currentData() if hasattr(self, "cmb_sort") \
            else "newest"
        items = list(self.plan.items)
        if order == "newest":
            items.sort(key=lambda i: (-i.added_epoch, i.display_name.lower()))
        elif order == "oldest":
            items.sort(key=lambda i: (i.added_epoch, i.display_name.lower()))
        elif order == "document":
            items.sort(key=lambda i: i.doc_index)
        else:
            items.sort(key=lambda i: i.display_name.lower())

        provider = QFileIconProvider()
        self.list.blockSignals(True)
        self.list.clear()
        self.rows = []
        for item in items:
            row = QListWidgetItem()
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)
            if item.available and item.media_type == "image":
                row.setIcon(QIcon(item.source))
            else:
                row.setIcon(provider.icon(QFileIconProvider.IconType.File))
            row.setText(self._row_text(item))
            row.setToolTip(item.source)
            self.list.addItem(row)
            self.rows.append((row, item.source))
        self.list.blockSignals(False)
        self._refresh_summary()

    def _row_text(self, item):
        parts = [item.display_name,
                 _SOURCE_LABELS.get(item.origin, item.origin),
                 _human_time(item.added_epoch, self.lang),
                 _human_size(item.size)]
        if not item.available:
            parts.append(tr("Missing", self.lang))
        return "   ·   ".join(parts)

    def _set_all(self, checked):
        self.list.blockSignals(True)
        for row, _src in self.rows:
            row.setCheckState(Qt.CheckState.Checked if checked
                             else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._refresh_summary()

    def _invert(self):
        self.list.blockSignals(True)
        for row, _src in self.rows:
            row.setCheckState(
                Qt.CheckState.Unchecked
                if row.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked)
        self.list.blockSignals(False)
        self._refresh_summary()

    def _selected_sources(self):
        return {src for row, src in self.rows
                if row.checkState() == Qt.CheckState.Checked}

    def _refresh_summary(self):
        chosen = self._selected_sources()
        size = sum(i.size for i in self.plan.items if i.source in chosen)
        count = len(chosen) + (1 if self.chk_text.isChecked() else 0)
        self.lbl_summary.setText(
            tr("%n selected · %s", self.lang).replace("%n", str(count))
            .replace("%s", _human_size(size)))
        self.btn_pack.setEnabled(bool(chosen) or self.chk_text.isChecked())

    # -- destination ---------------------------------------------------
    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("Choose folder…", self.lang), self.lbl_dest.text())
        if not folder:
            return
        self.custom_dir = folder
        self.cmb_dest.addItem(os.path.basename(folder) or folder, folder)
        self.cmb_dest.setCurrentIndex(self.cmb_dest.count() - 1)

    def resolve_destination(self):
        data = self.cmb_dest.currentData()
        if data in ("silo", None):
            return os.path.join(self.capture["silo_dir"], "exports")
        if data == "desktop":
            return os.path.join(os.path.expanduser("~"), "Desktop")
        if data == "documents":
            return os.path.join(os.path.expanduser("~"), "Documents",
                                "FastPrompter Exports")
        return str(data)

    def _update_dest_label(self):
        target = self.resolve_destination()
        self.lbl_dest.setText(target)
        self.lbl_dest.setToolTip(target)

    # -- result --------------------------------------------------------
    def _options(self):
        chosen = self._selected_sources()
        excluded = [i.source for i in self.plan.items if i.source not in chosen]
        return {
            "include_text": self.chk_text.isChecked(),
            "include_attachments": self.chk_attach.isChecked(),
            "hide_local_paths": self.cmb_port.currentData() is not False,
            "target_dir": self.resolve_destination(),
            "excluded": excluded,
            "keep_versions": self.spn_keep.value() if hasattr(self, "spn_keep") else 5,
        }

    def accept(self):
        options = self._options()
        if getattr(self.win, "_silo_bundle_remember_defaults", None):
            self.win._silo_bundle_remember_defaults(
                self.capture.get("silo_id"), {
                    "include_text": options["include_text"],
                    "include_attachments": options["include_attachments"],
                    "hide_local_paths": options["hide_local_paths"],
                    "keep_versions": options["keep_versions"],
                    "remember": self.chk_remember.isChecked(),
                    "destination": (options["target_dir"]
                                    if self.cmb_dest.currentData()
                                    not in ("silo", "desktop", "documents")
                                    else ""),
                })
        super().accept()


def show_bundle_dialog(main_win, capture):
    """Run the options dialog; return the chosen options, or None."""
    try:
        dlg = BundleOptionsDialog(main_win, capture)
    except Exception:
        return None
    if not dlg.exec():
        return None
    return dlg._options()
