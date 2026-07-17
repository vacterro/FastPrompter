"""Comprehensive, clickable help dialog for FastPrompter.

Opened from the "?" button in the header. Lists every hotkey (with the
user's actual rebound global hotkeys), mouse gesture, and feature.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout


def _rows(pairs):
    out = []
    for key, desc in pairs:
        out.append(
            f"<tr><td style='padding:2px 14px 2px 2px; white-space:nowrap;'>"
            f"<b>{key}</b></td><td style='padding:2px;'>{desc}</td></tr>"
        )
    return "".join(out)


def build_help_html(data) -> str:
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
    ])
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
    ])
    mouse_rows = _rows([
        ("Wheel over silos / snippets / archive", "Flip pages"),
        ("Ctrl+Wheel over silos", "Select previous / next silo"),
        ("Wheel over the tab bar", "Switch project"),
        ("Ctrl+Wheel in the editor", "Zoom the editor font"),
        ("Middle-click a silo", "Move it to the trash (text + files land in data/files/_trash)"),
        ("Hover a silo", "&#9989; tick, &#128193; files, &#128204; pin and &#128229; archive buttons appear"),
        ("Click &#9989; on a silo", "Mark it done — the tick stays until clicked again"),
        ("Click &#9112; on a ``` code fence", "Copy that code block to the clipboard"),
        ("Click &#9662; on a header / fence", "Fold (collapse) the section; right-click editor &rarr; Expand All Folds"),
        ("Alt+drop files on the Files panel", "Add .url links instead of copies"),
        ("Drag files over the editor", "A grid of drop zones appear: insert as text, "
                                       "link in text, copy to silo Files, or link in silo Files"),
        ("In the Files panel", "Del delete &middot; F2 rename &middot; Enter open &middot; "
                               "Ctrl+Shift+C copy path &middot; Ctrl+N new folder &middot; Ctrl+V clipboard&rarr;file"),
        ("Right-click a silo", "Transfer to project, replace from, move to bottom&hellip;"),
        ("Drop a silo ONTO another", "Nest it as a child (1 level; its files can merge into the parent)"),
        ("Shift+drop a silo onto another", "Swap their places"),
        ("Drag a silo between others", "Reorder — dragging a child out promotes it back to top level"),
        ("Right-click a parent silo", "Collapse / expand its children"),
        ("Left / right half-click a snippet", "Open with the cursor at start / end"),
        ("Click the line-number gutter", "Cycle margin marks: &#128308; &rarr; &#128998; &rarr; &#128312; &rarr; off"),
    ])
    features = (
        "<ul style='margin:4px 0 4px 16px; padding:0;'>"
        "<li><b>Silos</b> — up to 100 auto-saved scratchpads per project; pins, "
        "recency color tints, line counters, drag to reorder</li>"
        "<li><b>Snippets</b> — named text blocks per project tab; instant paste</li>"
        "<li><b>Projects</b> — up to 5 tabs, each with its own silos, snippets, archive</li>"
        "<li><b>Archive</b> — one click (&#128229;) stores the current silo or snippet</li>"
        "<li><b>Markdown</b> — live highlighting, clickable links &amp; checkboxes, "
        "auto-bullets (- + space, Enter continues), zebra stripes, line numbers</li>"
        "<li><b>Drop any file</b> — ~50 text formats load as plain text</li>"
        "<li><b>Code blocks</b> — ``` fences render monospace with syntax tints, "
        "auto line numbers and a one-click &#9112; copy button on the fence line</li>"
        "<li><b>File container</b> (&#128193;) — per-silo asset drawer: drop ANY "
        "files in, drag them out, preview images, open, export, link (.url), save "
        "clipboard as file. Explorer-style Icons / List / Details views. Plain folders "
        "under <code>data/files/&lt;project&gt;/&lt;silo-title&gt;/</code> (location "
        "configurable in settings) — fully readable outside FastPrompter. The &#128193; "
        "button shows a live file count; hover for a per-type size breakdown</li>"
        "<li><b>Folding</b> — collapse code blocks and # header sections with the "
        "&#9662; box; deleted-anchor escape hatch: right-click &rarr; Expand All Folds</li>"
        "<li><b>Trash, not delete</b> — clearing or trashing a silo writes its text to "
        "<code>data/files/_trash/</code> and moves its files there; nothing is destroyed</li>"
        "<li><b>Header template</b> — Settings &rarr; Header Fmt: {text}, {time}, {state} "
        "(Morning/Day/Evening/Night) — bold markers are yours to keep or drop</li>"
        "<li><b>Clock</b> — date + time with seconds, day word and an optional mini "
        "analog clock, all toggleable</li>"
        "<li><b>Scale</b> — 50&ndash;150% whole-UI scaling with readable minimums</li>"
        "<li><b>Sounds</b> — optional UI clicks and typewriter effect (settings &#9881;)</li>"
        "<li><b>Data</b> — SQLite in <code>data/</code> next to the app; daily Markdown "
        "backups in <code>Documents\\.fastprompter\\</code>; crash log next to the EXE</li>"
        "</ul>"
    )
    return (
        "<h2 style='margin:2px 0;'>FastPrompter Help</h2>"
        "<h3 style='margin:10px 0 2px 0;'>Global hotkeys <small>(rebindable in "
        "Settings &rarr; Keys, two slots each)</small></h3>"
        f"<table>{global_rows}</table>"
        "<h3 style='margin:10px 0 2px 0;'>In the app</h3>"
        f"<table>{app_rows}</table>"
        "<h3 style='margin:10px 0 2px 0;'>Mouse</h3>"
        f"<table>{mouse_rows}</table>"
        "<h3 style='margin:10px 0 2px 0;'>What everything does</h3>"
        f"{features}"
    )


class HelpDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setWindowTitle("FastPrompter — Help")
        self.setModal(False)
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(build_help_html(main_win.data))
        layout.addWidget(browser)
        btn = QPushButton("Close", self)
        btn.clicked.connect(self.close)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
