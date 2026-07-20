from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, 
    QLabel, QMessageBox, QListWidgetItem
)
from PyQt6.QtCore import Qt
import os
import shutil

class TrashDialog(QDialog):
    def __init__(self, main_win, trash_dir):
        super().__init__(main_win)
        self.main_win = main_win
        self.trash_dir = trash_dir
        self.setWindowTitle(self.tr("Manage Trash"))
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        
        lbl = QLabel(self.tr("Deleted silos and snippet texts are saved here."))
        layout.addWidget(lbl)
        
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        
        self.btn_restore = QPushButton(self.tr("Restore Selected"))
        self.btn_restore.clicked.connect(self._restore_selected)
        btn_layout.addWidget(self.btn_restore)
        
        self.btn_empty = QPushButton(self.tr("Empty Trash"))
        self.btn_empty.clicked.connect(self._empty_trash)
        btn_layout.addWidget(self.btn_empty)
        
        btn_close = QPushButton(self.tr("Close"))
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        
        self._load_trash()

    def tr(self, text):
        if hasattr(self.main_win, "tr"):
            return self.main_win.tr(text, getattr(self.main_win, "_current_lang", "EN"))
        return text

    def _load_trash(self):
        self.list_widget.clear()
        if not os.path.isdir(self.trash_dir):
            return
            
        for f in sorted(os.listdir(self.trash_dir), reverse=True):
            if f.endswith(".md"):
                item = QListWidgetItem(f)
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(self.trash_dir, f))
                self.list_widget.addItem(item)

    def _restore_selected(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
            
        item = items[0]
        filepath = item.data(Qt.ItemDataRole.UserRole)
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
                
            # Create a new silo with this text
            if hasattr(self.main_win, "add_silo"):
                self.main_win.add_silo(text)
            elif hasattr(self.main_win, "data") and "temp_presets" in self.main_win.data:
                self.main_win.data["temp_presets"].insert(0, text)
                self.main_win.mark_dirty()
                if hasattr(self.main_win, "refresh_temp_presets"):
                    self.main_win.refresh_temp_presets()
            
            # Delete the restored file
            os.remove(filepath)
            
            QMessageBox.information(self, self.tr("Success"), self.tr("Silo restored successfully."))
            self._load_trash()
            
        except Exception as e:
            QMessageBox.warning(self, self.tr("Error"), f"{self.tr('Failed to restore:')}\n{e}")

    def _empty_trash(self):
        reply = QMessageBox.question(
            self, 
            self.tr("Empty Trash"), 
            self.tr("Do you want to delete ALL trash?\n\nYes: Delete text and files.\nNo: Delete text only, keep files."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        
        if reply == QMessageBox.StandardButton.Cancel:
            return
            
        if not os.path.isdir(self.trash_dir):
            return
            
        delete_all = (reply == QMessageBox.StandardButton.Yes)
        
        try:
            for f in os.listdir(self.trash_dir):
                path = os.path.join(self.trash_dir, f)
                if os.path.isfile(path) and f.endswith(".md"):
                    os.remove(path)
                elif delete_all and os.path.isdir(path):
                    shutil.rmtree(path)
            self._load_trash()
            QMessageBox.information(self, self.tr("Success"), self.tr("Trash emptied."))
        except Exception as e:
            QMessageBox.warning(self, self.tr("Error"), f"{self.tr('Failed to empty trash:')}\n{e}")
