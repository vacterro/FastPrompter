import os

from PyQt6.QtCore import Qt
from fastprompter.core.translations import tr
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
        self.main_win.save_data_to_db(force=True)
        path, _ = QFileDialog.getSaveFileName(self, tr("Backup Database", self.lang), "prompts_backup.db", "SQLite DB (*.db)")
        if path:
            try:
                import sqlite3
                source_conn = sqlite3.connect(self.main_win.state.db_path)
                dest_conn = sqlite3.connect(path)
                source_conn.backup(dest_conn)
                dest_conn.close()
                source_conn.close()
                QMessageBox.information(self, tr("Success", self.lang), tr("Database backed up to:\n{}", self.lang).format(path))
            except Exception as e:
                QMessageBox.critical(self, tr("Error", self.lang), tr("Failed to backup:\n{}", self.lang).format(e))

    def export_silos(self):
        fmt = self.combo_format.currentText()
        path = QFileDialog.getExistingDirectory(self, tr("Select Export Directory", self.lang))
        if not path:
            return

        try:
            self.main_win.save_data_to_db(force=True)

            # Export Temp Presets (Silos)
            for i, text in enumerate(self.main_win.data.get("temp_presets", [])):
                if text.strip():
                    filename = os.path.join(path, f"Silo_{i+1}{fmt}")
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(text)

            # Export Archive Temp Presets
            for i, text in enumerate(self.main_win.data.get("archive_temp_presets", [])):
                if text.strip():
                    filename = os.path.join(path, f"Archive_Silo_{i+1}{fmt}")
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(text)

            QMessageBox.information(self, tr("Success", self.lang), tr("Silos exported to:\n{}", self.lang).format(path))
        except Exception as e:
            QMessageBox.critical(self, tr("Error", self.lang), tr("Failed to export:\n{}", self.lang).format(e))
