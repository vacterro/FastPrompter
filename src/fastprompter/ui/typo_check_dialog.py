"""TypoCheckDialog — the whole-project typecheck report.

Right-click the project tab -> \"Check Typos in this project…\". Scans every
silo of the current project with the SAME dictionary the live underline
uses (core/typecheck.py), groups unknown words per silo, and lets the user
add words to the dictionary from the report.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from fastprompter.core.translations import tr


class TypoCheckDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Typecheck — this project", self.lang))
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color: #808080;")
        layout.addWidget(self.lbl_hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            tr("Silo", self.lang),
            tr("Word", self.lang),
            tr("Line", self.lang),
        ])
        self.tree.setColumnWidth(0, 180)
        self.tree.setColumnWidth(1, 220)
        layout.addWidget(self.tree, 1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton(tr("✓ Add selected to dictionary", self.lang))
        self.btn_add.setToolTip(tr(
            "The chosen words will never be flagged again (also in the "
            "live editor underlines).", self.lang))
        self.btn_add.clicked.connect(self.add_selected)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch(1)
        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._scan()

    # ------------------------------------------------------------------
    def _scan(self):
        """Rebuild the report from the project's silos."""
        from fastprompter.core import typecheck as tc
        presets = self.main_win.data.get("temp_presets") or []
        dictionary = self.main_win._typo_dictionary()
        total = 0
        self.tree.clear()
        for slot, text in enumerate(presets):
            if not text or not text.strip():
                continue
            found: dict[str, int] = {}
            for line_no, line in enumerate(text.split("\n"), start=1):
                for word, _s, _e in tc.iter_tokens(line):
                    if dictionary.unknown(word):
                        found.setdefault(word, line_no)
            if not found:
                continue
            parent = QTreeWidgetItem([f"{slot + 1}", "", ""])
            for word in sorted(found):
                child = QTreeWidgetItem(["", word, str(found[word])])
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
            total += len(found)
        self.tree.expandAll()
        if total == 0:
            self.lbl_hint.setText(tr("No unknown words found. 🎉", self.lang))
            self.btn_add.setEnabled(False)
        else:
            self.lbl_hint.setText(tr(
                "{} unknown word(s) in this project. Select one or more and "
                "add them to your dictionary, or fix them in the silos.",
                self.lang).format(total))
            self.btn_add.setEnabled(True)

    def add_selected(self):
        added = 0
        for item in self.tree.selectedItems():
            word = item.text(1)
            if word:
                self.main_win._add_typo_word(word)
                added += 1
        if added:
            self._scan()
