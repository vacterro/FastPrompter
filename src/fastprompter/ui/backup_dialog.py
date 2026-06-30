from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QGroupBox, QRadioButton, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt
import os
import shutil

class BackupDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.main_win = main_win
        self.setWindowTitle("Backup & Export Settings")
        self.setMinimumWidth(350)
        
        layout = QVBoxLayout(self)
        
        # Backup Database Group
        db_group = QGroupBox("Backup Full Database")
        db_layout = QVBoxLayout(db_group)
        lbl_db = QLabel("Creates an exact copy of the local_data_v15.db file containing all settings, silos, and snippets.")
        lbl_db.setWordWrap(True)
        db_layout.addWidget(lbl_db)
        
        btn_backup_db = QPushButton("Backup Database (.db)")
        btn_backup_db.clicked.connect(self.backup_database)
        db_layout.addWidget(btn_backup_db)
        layout.addWidget(db_group)
        
        # Export Silos Group
        export_group = QGroupBox("Export Silos & Text")
        export_layout = QVBoxLayout(export_group)
        
        lbl_export = QLabel("Export all Silo contents to readable text formats.")
        lbl_export.setWordWrap(True)
        export_layout.addWidget(lbl_export)
        
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems([".txt", ".md"])
        format_layout.addWidget(self.combo_format)
        format_layout.addStretch()
        export_layout.addLayout(format_layout)
        
        btn_export = QPushButton("Export All Silos")
        btn_export.clicked.connect(self.export_silos)
        export_layout.addWidget(btn_export)
        
        layout.addWidget(export_group)
        
        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)
        
        # Apply theme
        self.setStyleSheet(self.main_win.styleSheet())
        
    def backup_database(self):
        self.main_win.save_data_to_db(force=True)
        path, _ = QFileDialog.getSaveFileName(self, "Backup Database", "prompts_backup.db", "SQLite DB (*.db)")
        if path:
            try:
                import sqlite3
                source_conn = sqlite3.connect(self.main_win.state.db_path)
                dest_conn = sqlite3.connect(path)
                source_conn.backup(dest_conn)
                dest_conn.close()
                source_conn.close()
                QMessageBox.information(self, "Success", f"Database backed up to:\\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to backup:\\n{str(e)}")

    def export_silos(self):
        fmt = self.combo_format.currentText()
        path = QFileDialog.getExistingDirectory(self, "Select Export Directory")
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
            
            QMessageBox.information(self, "Success", f"Silos exported to:\\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export:\\n{str(e)}")
