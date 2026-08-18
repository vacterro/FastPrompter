import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.translations import tr


class BackupDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.main_win = main_win
        self.lang = getattr(self.main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Backup & Export Settings", self.lang))
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # Backup Database Group
        db_group = QGroupBox(tr("Backup Full Database", self.lang))
        db_layout = QVBoxLayout(db_group)
        lbl_db = QLabel(tr("Creates an exact copy of the local_data_v15.db file containing all settings, silos, and snippets.", self.lang))
        lbl_db.setWordWrap(True)
        db_layout.addWidget(lbl_db)

        btn_backup_db = QPushButton(tr("Backup Database (.db)", self.lang))
        btn_backup_db.clicked.connect(self.backup_database)
        db_layout.addWidget(btn_backup_db)
        layout.addWidget(db_group)

        # Export Silos Group
        export_group = QGroupBox(tr("Export Silos & Text", self.lang))
        export_layout = QVBoxLayout(export_group)

        lbl_export = QLabel(tr("Export all Silo contents to readable text formats.", self.lang))
        lbl_export.setWordWrap(True)
        export_layout.addWidget(lbl_export)

        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel(tr("Format:", self.lang)))
        self.combo_format = QComboBox()
        self.combo_format.addItems([".txt", ".md"])
        format_layout.addWidget(self.combo_format)
        format_layout.addStretch()
        export_layout.addLayout(format_layout)

        btn_export = QPushButton(tr("Export All Silos", self.lang))
        btn_export.clicked.connect(self.export_silos)
        export_layout.addWidget(btn_export)

        layout.addWidget(export_group)

        # Close button
        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

        # Apply theme
        self.setStyleSheet(self.main_win.styleSheet())

    def backup_database(self):
        # P0: the manual backup must capture the AUTHORITATIVE current state.
        # If the SQLite save fails, abort before opening/publishing any
        # destination — otherwise the backup would omit the visible unsaved
        # edits while the UI reports success. No destination is created.
        if not self.main_win.save_data_to_db(force=True):
            QMessageBox.critical(
                self, tr("Error", self.lang),
                tr("Cannot back up: the current state could not be saved to "
                   "the database.", self.lang))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Backup Database", self.lang), "prompts_backup.db", "SQLite DB (*.db)")
        if not path:
            return
        try:
            from fastprompter.core.state import (
                RestoreError,
                _backup_atomically,
                _same_file,
            )

            db_path = self.main_win.state.db_path
            if _same_file(db_path, path):
                QMessageBox.warning(self, tr("Error", self.lang),
                                    tr("Source and destination are the same file.", self.lang))
                return
            import sqlite3
            src = sqlite3.connect(db_path)
            try:
                # the shared safe primitive: SQLite backup API into a temp
                # sibling, the candidate VALIDATED before the swap, then
                # atomically published — a partial or corrupt backup is never
                # exposed under the requested name
                _backup_atomically(src, path)
            finally:
                src.close()
            QMessageBox.information(self, tr("Success", self.lang),
                                    tr("Database backed up to:\n{}", self.lang).format(path))
        except RestoreError as e:
            from fastprompter.core.logging import logger
            logger.exception("manual database backup failed validation: %s", e)
            QMessageBox.critical(self, tr("Error", self.lang),
                                 tr("Backup failed validation and was removed:\n{}", self.lang).format(e))
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        except Exception as e:
            QMessageBox.critical(self, tr("Error", self.lang),
                                 tr("Failed to backup:\n{}", self.lang).format(e))

    def export_silos(self):
        fmt = self.combo_format.currentText()
        path = QFileDialog.getExistingDirectory(self, tr("Select Export Directory", self.lang))
        if not path:
            return

        try:
            self.main_win.save_data_to_db(force=True)
            from fastprompter.utils.path_safety import alloc_fs_names

            data = self.main_win.data
            # one collision-free filesystem component per project name, so
            # two logical names that differ only by case or hostile
            # characters can never silently share an export directory
            all_cats = [c for c in data.get("cats_order", []) if isinstance(c, str)]
            comps = alloc_fs_names(all_cats)

            def comp_for(cat):
                return comps.get(cat, self.main_win.state._sanitize_cat_name(cat))

            # Export Temp Presets (Silos)
            for cat, slots in data.get("temp_presets_all", {}).items():
                cat_dir = os.path.join(path, comp_for(cat))
                os.makedirs(cat_dir, exist_ok=True)
                for i, text in enumerate(slots):
                    if text.strip():
                        filename = os.path.join(cat_dir, f"Silo_{i+1}{fmt}")
                        with open(filename, 'w', encoding='utf-8') as f:
                            f.write(text)

            # Export Archive Temp Presets
            for cat, slots in data.get("archive_temp_presets_all", {}).items():
                cat_dir = os.path.join(path, comp_for(cat))
                os.makedirs(cat_dir, exist_ok=True)
                for i, text in enumerate(slots):
                    if text.strip():
                        filename = os.path.join(cat_dir, f"Archive_Silo_{i+1}{fmt}")
                        with open(filename, 'w', encoding='utf-8') as f:
                            f.write(text)

            QMessageBox.information(self, tr("Success", self.lang), tr("Silos exported to:\n{}", self.lang).format(path))
        except Exception as e:
            QMessageBox.critical(self, tr("Error", self.lang), tr("Failed to export:\n{}", self.lang).format(e))
