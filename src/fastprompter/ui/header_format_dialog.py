"""Comprehensive editor for the Ctrl+E header template.

The template is a plain string with placeholders the editor substitutes when
you press Ctrl+E on a line:
    {text}  — the line's own text
    {time}  — the date/time stamp (DD.MM - hh:mm, honoring your date settings)
    {state} — the time-of-day word (Morning / Day / Evening / Night)
Everything else (markdown markers **, __, *, leading #, punctuation) is kept
verbatim, so the user has full control over the look.
"""

import datetime
import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.translations import tr

DEFAULT_TEMPLATE = "{text} ({time})"

# A Ctrl+E line always starts with "# ", which the editor already renders
# bold + gold + larger. Wrapping the title in **__ __** on top of that only
# prints literal ** __ markers over an already-bold header — pure clutter.
# So every preset is markerless: the header IS the bold.
_PRESETS = [
    ("Title + time", "{text} ({time})"),
    ("Day + time", "{text} — {state} {time}"),
    ("Dotted", "{text}  ·  {time}"),
    ("Dash + time", "{text} — {time}"),
    ("Title only", "{text}"),
]

# Old marker-heavy templates -> their clean equivalents; used to migrate a
# format the user saved before this cleanup so their asterisks disappear too.
LEGACY_TEMPLATE_MIGRATION = {
    "**__{text}__** ({time})": "{text} ({time})",
    "**{text}** — {state} {time}": "{text} — {state} {time}",
    "__{text}__ ({time})": "{text} ({time})",
    "**{text}** ({time})": "{text} ({time})",
}


class HeaderFormatDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self._lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Ctrl+E Header Format", self._lang))
        self.setModal(True)
        self.setMinimumWidth(440)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel(tr(
            "Design how Ctrl+E rewrites a line. Use the placeholders below;\n"
            "everything else (markdown, #, punctuation) is kept exactly.",
            self._lang)))

        # template field
        template = self.main_win.data.get("ctrl_e_format", DEFAULT_TEMPLATE)
        if template in LEGACY_TEMPLATE_MIGRATION:
            template = LEGACY_TEMPLATE_MIGRATION[template]
            self.main_win.data["ctrl_e_format"] = template
            self.main_win.mark_dirty()
            
        self.edit = QLineEdit(template)
        self.edit.textChanged.connect(self._update_preview)
        root.addWidget(self.edit)

        # placeholder + markdown insert buttons
        ins = QHBoxLayout()
        ins.setSpacing(4)
        for label, token in (("{text}", "{text}"), ("{time}", "{time}"),
                             ("{state}", "{state}")):
            b = QPushButton(label)
            b.setToolTip(tr("Insert this placeholder at the cursor", self._lang))
            b.clicked.connect(lambda _c, t=token: self._insert(t))
            ins.addWidget(b)
        for label, wrap in (("B", "**"), ("I", "*"), ("U", "__"), ("S", "~~")):
            b = QPushButton(label)
            b.setFixedWidth(28)
            b.setToolTip(tr("Wrap the selection in this markdown marker", self._lang))
            b.clicked.connect(lambda _c, m=wrap: self._wrap(m))
            ins.addWidget(b)
        ins.addStretch(1)
        root.addLayout(ins)

        # placeholder legend
        legend = QLabel(tr(
            "{text} = the line's text   ·   {time} = timestamp   ·   "
            "{state} = Morning/Day/Evening/Night", self._lang))
        legend.setWordWrap(True)
        legend.setStyleSheet("color: #7A6838;")
        root.addWidget(legend)

        # presets
        prow = QHBoxLayout()
        prow.setSpacing(4)
        prow.addWidget(QLabel(tr("Presets:", self._lang)))
        for name, tmpl in _PRESETS:
            b = QPushButton(name)
            b.clicked.connect(lambda _c, t=tmpl: self.edit.setText(t))
            prow.addWidget(b)
        prow.addStretch(1)
        root.addLayout(prow)

        # live preview
        root.addWidget(QLabel(tr("Preview:", self._lang)))
        self.preview = QLabel("")
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            "background:#1A0F05; color:#D4B87A; border:1px solid #4A3820; padding:6px;")
        root.addWidget(self.preview)

        # buttons
        brow = QHBoxLayout()
        reset = QPushButton(tr("Reset to Default", self._lang))
        reset.clicked.connect(lambda: self.edit.setText(DEFAULT_TEMPLATE))
        brow.addWidget(reset)
        brow.addStretch(1)
        cancel = QPushButton(tr("Cancel", self._lang))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("OK", self._lang))
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        brow.addWidget(cancel)
        brow.addWidget(ok)
        root.addLayout(brow)

        self._update_preview()

    def _insert(self, token):
        self.edit.insert(token)
        self.edit.setFocus()

    def _wrap(self, marker):
        if self.edit.hasSelectedText():
            sel = self.edit.selectedText()
            start = self.edit.selectionStart()
            full = self.edit.text()
            self.edit.setText(full[:start] + marker + sel + marker + full[start + len(sel):])
        else:
            self.edit.insert(marker + marker)
        self.edit.setFocus()

    def sample_line(self, template):
        """Render the template with sample values — matches apply_header_timestamp."""
        now = datetime.datetime.now()
        h = now.hour
        state = ("Morning" if 5 <= h < 12 else "Day" if 12 <= h < 17
                 else "Evening" if 17 <= h < 22 else "Night")
        d = self.main_win.data
        m_fmt = "%d %b" if d.get("date_text_month", "False") == "True" else "%d.%m"
        t_fmt = self.main_win._clock_time_fmt()
        ts = now.strftime(f"{m_fmt} - {t_fmt}")
        if "{state}" in template:
            time_str = ts
        else:
            time_str = f"{state} {ts}" if d.get("date_daypart", "True") == "True" else ts
        line = (template.replace("{text}", tr("Sample title", self._lang))
                .replace("{time}", time_str).replace("{state}", state))
        return line if line.startswith("# ") else f"# {line}"

    def _preview_html(self, line):
        """Style the sample line the way the editor's own highlighter would:
        bold/underline/italic/strike applied IN PLACE over the markers (they
        stay visible, same as markdown_highlighter.py never hides them), plus
        the header line itself is always bold (Ctrl+E lines start with '# ',
        which the highlighter's H1 rule always bolds)."""
        text = html.escape(line)
        text = re.sub(r"(~~[^~\n]+~~)", r"<s>\1</s>", text)
        text = re.sub(r"(__[^_\n]+__)", r"<u>\1</u>", text)
        text = re.sub(r"(\*\*.*?\*\*)", r"<b>\1</b>", text)
        text = re.sub(r"(\*(?!\*).*?\*(?!\*))", r"<i>\1</i>", text)
        return f"<b>{text}</b>"

    def _update_preview(self):
        self.preview.setText(self._preview_html(self.sample_line(self.edit.text())))

    def _accept(self):
        self.main_win.data["ctrl_e_format"] = self.edit.text()
        self.main_win.mark_dirty()
        if hasattr(self.main_win, "le_hdr_fmt"):
            self.main_win.le_hdr_fmt.setText(self.edit.text())
        self.accept()
