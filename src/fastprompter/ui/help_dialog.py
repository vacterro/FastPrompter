"""Comprehensive, clickable help dialog for FastPrompter.

Opened from the "?" button in the header. Lists every hotkey (with the
user's actual rebound global hotkeys), mouse gesture, and feature.
Now supports EN/RU translation.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout

from fastprompter.core.translations import tr


def _rows(pairs, lang):
    out = []
    for key, desc in pairs:
        out.append(
            f"<tr><td style='padding:2px 14px 2px 2px; white-space:nowrap;'>"
            f"<b>{key}</b></td><td style='padding:2px;'>{tr(desc, lang)}</td></tr>"
        )
    return "".join(out)


def build_help_html(data, lang="EN") -> str:
    g = data.get
    global_rows = _rows([
        (f"{g('global_hotkey', 'Alt+X')} / {g('global_hotkey_alt', 'F15')}",
         "Show / hide FastPrompter from anywhere"),
        (g("pie_menu_hotkey", "Shift+Alt+X"), "Quick List pie menu at the cursor"),
        (g("toggle_sidebar_hotkey", "Alt+D"), "Show window + toggle the sidebar"),
        (g("lock_window_hotkey", "Alt+S"), "Lock / unlock window size & position"),
        (g("always_on_top_hotkey", "Alt+E"), "Toggle always-on-top"),
        (g("hide_on_clickout_hotkey", "Alt+A"), "Toggle Hide on Click-Out"),
        ("F1&ndash;F10 (global)", "Paste snippet 1&ndash;10 into the active app"),
    ], lang)
    app_rows = _rows([
        ("Ctrl+N", "New empty silo at the top (max 5 blanks)"),
        ("Alt+Up / Alt+Down", "Previous / next silo"),
        ("Ctrl+1&ndash;Ctrl+0", "Jump to silo 1&ndash;10"),
        ("F1&ndash;F10", "Paste snippet 1&ndash;10 into the editor"),
        ("Ctrl+S", "Save text as snippet / update the edited snippet"),
        ("Ctrl+W", "Insert a spaced --- divider and start a fresh bullet"),
        ("Ctrl+E", "Header the line: # + bold + underline + timestamp, "
                   "then jump 2 lines down onto a fresh &bull; bullet"),
        ("Ctrl+Return", "Toggle [ ] checkboxes on the line / selection"),
        ("Ctrl+B / Ctrl+I / Ctrl+U", "Bold / Italic / Underline"),
        ("Ctrl+F / Ctrl+H", "Find / Find &amp; Replace"),
        ("Ctrl+Z / Ctrl+Shift+Z", "Undo / redo — text <i>and</i> silo actions "
                                  "(clear, delete, move, pin, archive, tabs)"),
        ("Ctrl+Q", "Snap the window through screen corners"),
        ("Ctrl+D", "Zen / focus mode (hide all chrome)"),
        ("Ctrl+Shift+S", "Export the current silo to a .txt/.md file"),
        ("Ctrl+Plus / Ctrl+Minus", "Fine-tune the UI scale"),
        ("Esc", "Close search bar; press again to hide &amp; save"),
        ("Ctrl+Alt+Shift+Q", "Quit completely"),
    ], lang)
    mouse_rows = _rows([
        ("Wheel over silos / snippets / archive", "Flip pages"),
        ("Ctrl+Wheel over silos", "Select previous / next silo"),
        ("Wheel over the tab bar", "Switch project"),
        ("Ctrl+Wheel in the editor", "Zoom the editor font"),
        ("Middle-click a silo", "Move it to the trash (text + files land in data/files/_trash)"),
        ("Hover a silo",
         "&#9989; tick, &#128193; files, &#128204; pin and &#128229; archive buttons appear"),
        ("Click &#9989; on a silo", "Mark it done — the tick stays until clicked again"),
        ("Click &#9112; on a ``` code fence", "Copy that code block to the clipboard"),
        ("Click &#9662; on a header / fence",
         "Fold (collapse) the section; right-click editor &rarr; Expand All Folds"),
        ("Alt+drop files on the Files panel", "Add .url links instead of copies"),
        ("Drag files over the editor",
         "A grid of drop zones appear: insert as text, "
         "link in text, copy to silo Files, or link in silo Files"),
        ("In the Files panel",
         "Del delete &middot; F2 rename &middot; Enter open &middot; "
         "Ctrl+Shift+C copy path &middot; Ctrl+N new folder &middot; Ctrl+V clipboard&rarr;file"),
        ("Right-click a silo", "Transfer to project, replace from, move to bottom&hellip;"),
        ("Drop a silo ONTO another",
         "Nest it as a child (1 level; its files can merge into the parent)"),
        ("Shift+drop a silo onto another", "Swap their places"),
        ("Drag a silo between others",
         "Reorder — dragging a child out promotes it back to top level"),
        ("Right-click a parent silo", "Collapse / expand its children"),
        ("Left / right half-click a snippet", "Open with the cursor at start / end"),
        ("Click the line-number gutter",
         "Cycle margin marks: &#128308; &rarr; &#128998; &rarr; &#128312; &rarr; off"),
    ], lang)
    features = (
        "<ul style='margin:4px 0 4px 16px; padding:0;'>"
        f"<li><b>{tr('Silos', lang)}</b> — {tr('up to 100 auto-saved scratchpads per project; pins, recency color tints, line counters, drag to reorder', lang)}</li>"
        f"<li><b>{tr('Snippets', lang)}</b> — {tr('named text blocks per project tab; instant paste', lang)}</li>"
        f"<li><b>{tr('Projects', lang)}</b> — {tr('up to 5 tabs, each with its own silos, snippets, archive', lang)}</li>"
        f"<li><b>{tr('Archive', lang)}</b> — {tr('one click stores the current silo or snippet', lang)}</li>"
        f"<li><b>{tr('Markdown', lang)}</b> — {tr('live highlighting, clickable links &amp; checkboxes, auto-bullets (- + space, Enter continues), zebra stripes, line numbers', lang)}</li>"
        f"<li><b>{tr('Drop any file', lang)}</b> — {tr('~50 text formats load as plain text', lang)}</li>"
        f"<li><b>{tr('Code blocks', lang)}</b> — {tr('``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line', lang)}</li>"
        f"<li><b>{tr('File container', lang)}</b> (&#128193;) — {tr('per-silo asset drawer: drop ANY files in, drag them out, preview images, open, export, link (.url), save clipboard as file. Explorer-style Icons / List / Details views', lang)}. "
        f"{tr('Plain folders under', lang)} <code>data/files/&lt;project&gt;/&lt;silo-title&gt;/</code> "
        f"({tr('location configurable in settings', lang)}) "
        f"&mdash; {tr('fully readable outside FastPrompter', lang)}.</li>"
        f"<li><b>{tr('Folding', lang)}</b> &mdash; {tr('collapse code blocks and # header sections with the fold box; right-click &rarr; Expand All Folds', lang)}</li>"
        f"<li><b>{tr('Trash, not delete', lang)}</b> &mdash; {tr('clearing or trashing a silo writes its text to data/files/_trash/ and moves its files there; nothing is destroyed', lang)}</li>"
        f"<li><b>{tr('Header template', lang)}</b> &mdash; {tr('Settings &rarr; Header Fmt: {{text}}, {{time}}, {{state}} (Morning/Day/Evening/Night) — bold markers are yours to keep or drop', lang)}</li>"
        f"<li><b>{tr('Clock', lang)}</b> &mdash; {tr('date + time with seconds, day word and an optional mini analog clock, all toggleable', lang)}</li>"
        f"<li><b>{tr('Scale', lang)}</b> &mdash; {tr('50&ndash;150% whole-UI scaling with readable minimums', lang)}</li>"
        f"<li><b>{tr('Sounds', lang)}</b> &mdash; {tr('optional UI clicks and typewriter effect', lang)}</li>"
        f"<li><b>{tr('Data', lang)}</b> &mdash; {tr('SQLite next to the app; daily Markdown backups in Documents; crash log next to the EXE', lang)}</li>"
        "</ul>"
    )
    return (
        f"<h2 style='margin:2px 0;'>{tr('FastPrompter Help', lang)}</h2>"
        f"<h3 style='margin:10px 0 2px 0;'>{tr('Global hotkeys', lang)} <small>"
        f"({tr('rebindable in Settings', lang)} &rarr; {tr('Keys', lang)}, "
        f"{tr('two slots each', lang)})</small></h3>"
        f"<table>{global_rows}</table>"
        f"<h3 style='margin:10px 0 2px 0;'>{tr('In the app', lang)}</h3>"
        f"<table>{app_rows}</table>"
        f"<h3 style='margin:10px 0 2px 0;'>{tr('Mouse', lang)}</h3>"
        f"<table>{mouse_rows}</table>"
        f"<h3 style='margin:10px 0 2px 0;'>{tr('What everything does', lang)}</h3>"
        f"{features}"
    )


class HelpDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self._lang = getattr(main_win, '_current_lang', 'EN')
        self.setWindowTitle(tr("FastPrompter — Help", self._lang))
        self.setModal(False)
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(build_help_html(main_win.data, self._lang))
        layout.addWidget(browser)
        btn = QPushButton(tr("Close", self._lang), self)
        btn.clicked.connect(self.close)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
