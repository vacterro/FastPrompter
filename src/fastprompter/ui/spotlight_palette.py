import sys
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QListWidget, 
                             QListWidgetItem, QApplication)
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont

class SpotlightPalette(QWidget):
    def __init__(self, data_ref, parent=None):
        super().__init__(parent)
        self.data = data_ref
        
        # Frameless, stay on top, popup
        self.setWindowFlags(
            Qt.WindowType.Popup | 
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint
        )
        
        self.setFixedSize(600, 400)
        
        # Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Search Box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search snippets... (Press Enter to Copy, Esc to close)")
        self.search_input.setFixedHeight(40)
        self.layout.addWidget(self.search_input)
        
        # Results List
        self.results_list = QListWidget()
        self.layout.addWidget(self.results_list)
        
        # Styling (Vintage Dark forced)
        self.setStyleSheet("""
            QWidget {
                background-color: #141414;
                color: #c0c0c0;
                font-family: Verdana;
                font-size: 12px;
                border: 2px solid #5a7a96;
            }
            QLineEdit {
                background-color: #000000;
                color: #ffffff;
                border: none;
                border-bottom: 2px solid #5a7a96;
                padding: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QListWidget {
                background-color: #141414;
                border: none;
                outline: none;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #202020;
            }
            QListWidget::item:selected {
                background-color: #5a7a96;
                color: #000000;
                font-weight: bold;
            }
        """)
        
        # Events
        self.search_input.textChanged.connect(self.filter_snippets)
        self.results_list.itemActivated.connect(self.on_item_activated)
        self.search_input.installEventFilter(self)
        
    def showEvent(self, event):
        self.search_input.clear()
        self.filter_snippets("")
        self.search_input.setFocus()
        super().showEvent(event)
        
    def filter_snippets(self, query):
        self.results_list.clear()
        query = query.lower()
        
        cats = self.data.get("categories", {})
        for cat_name, slots in cats.items():
            for idx, slot in enumerate(slots):
                if slot and "name" in slot and "text" in slot:
                    name = slot["name"]
                    text = slot["text"]
                    
                    if query in name.lower() or query in text.lower() or not query:
                        preview = text.replace('\n', ' ')[:60]
                        item_text = f"[{cat_name}] {name} - {preview}..."
                        item = QListWidgetItem(item_text)
                        # Store the actual text in the item's data
                        item.setData(Qt.ItemDataRole.UserRole, text)
                        self.results_list.addItem(item)
                        
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)
            
    def eventFilter(self, obj, event):
        if obj == self.search_input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                # Forward up/down to the list
                QApplication.sendEvent(self.results_list, event)
                return True
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Trigger selected
                current = self.results_list.currentItem()
                if current:
                    self.on_item_activated(current)
                return True
            elif key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)
        
    def on_item_activated(self, item):
        text = item.data(Qt.ItemDataRole.UserRole)
        QApplication.clipboard().setText(text)
        self.hide()
