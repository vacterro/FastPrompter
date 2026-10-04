"""Comprehensive, clickable help dialog for FastPrompter.

Opened from the "?" button in the header. Lists every hotkey (with the
user's actual rebound global hotkeys), mouse gesture, and feature.
Now supports EN/RU translation.
"""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

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
        (g("lock_window_hotkey", "Alt+E"), "Lock / unlock window size & position"),
        (g("always_on_top_hotkey", "Alt+S"), "Toggle always-on-top"),
        (g("hide_on_clickout_hotkey", "Alt+A"), "Toggle Hide on Click-Out"),
        ("F1&ndash;F10 (global)", "Paste snippet 1&ndash;10 into the active app"),
    ], lang)
    def hk(key, default):
        """The sequence the user actually has, for a configurable hk_* key.

        The sheet used to hardcode Ctrl+N / Ctrl+F / Ctrl+Z ... and so stayed
        wrong the moment a key was rebound in the Shortcut settings, and it
        omitted the keys T-1335 made rebindable. global_rows above already
        read their sequences out of data; these do the same. The defaults are
        the shipped ones from ui.hotkey_spec, not a private copy.
        """
        return g(key, default) or default

    app_rows = _rows([
        (hk("hk_new_snippet", "Ctrl+N"), "New empty silo at the top"),
        ("Alt+Up / Alt+Down", "Previous / next silo"),
        ("Ctrl+1&ndash;Ctrl+0", "Jump to silo 1&ndash;10"),
        ("F1&ndash;F10 / Ctrl+Shift+1&ndash;9", "Paste snippet 1&ndash;10 into the editor"),
        (hk("hk_save_snippet", "Ctrl+S"), "Save text as snippet / update the edited snippet"),
        (hk("hk_divider", "Ctrl+W"), "Insert a spaced --- divider (toolbar Line command)"),
        ("Alt+W", "Insert a spaced --- divider and start a fresh &bull; bullet (old behavior)"),
        (hk("hk_header", "Ctrl+E"), "Header the line: # + bold + underline + timestamp, "
                   "then jump 2 lines down onto a fresh &bull; bullet"),
        ("Ctrl+Return", "Toggle [ ] checkboxes on the line / selection"),
        (f"{hk('hk_bold', 'Ctrl+B')} / {hk('hk_italic', 'Ctrl+I')} / "
         f"{hk('hk_underline', 'Ctrl+U')}", "Bold / Italic / Underline"),
        ("Ctrl+T", "Strikethrough text"),
        ("Alt+Backspace", "Delete the previous word or selected text"),
        (f"{hk('hk_find', 'Ctrl+F')} / {hk('hk_replace', 'Ctrl+H')}",
         "Find / Find &amp; Replace"),
        (f"{hk('hk_undo', 'Ctrl+Z')} / Ctrl+Shift+Z", "Undo / redo — text <i>and</i> silo actions "
                                  "(clear, delete, move, pin, archive, tabs)"),
        (hk("hk_snap", "Ctrl+Q"), "Snap the window through screen corners"),
        (hk("hk_focus", "Ctrl+D"), "Zen / focus mode (hide all chrome)"),
        (hk("hk_export_silo", "Ctrl+Shift+S"), "Export the current silo to a .txt/.md file"),
        (hk("hk_pack_silo", "Ctrl+Shift+P"), "Pack the current silo into one portable ZIP "
                                "and copy it to the clipboard"),
        ("Ctrl+Plus / Ctrl+Minus", "Fine-tune the UI scale"),
        (hk("hk_timers", "Ctrl+Shift+T"), "Open Timers"),
        (hk("hk_hashtags", "Alt+Shift+T"), "Open Hashtags"),
        (hk("hk_audio_mute", "Ctrl+M"), "Master Mute"),
        (hk("hk_quote", "Ctrl+Shift+Q"), "Toggle Quote Conversion"),
        (hk("hk_line_nums", "Alt+Z"), "Toggle Line Numbers"),
        (hk("hk_settings", "Alt+`"), "Toggle Mini Settings"),
        ("Esc", "Close search bar; press again to hide &amp; save"),
        (hk("hk_quit", "Ctrl+Alt+Shift+Q"), "Quit completely"),
    ], lang)
    mouse_rows = _rows([
        ("Wheel over silos / snippets / archive", "Flip pages"),
        ("Ctrl+Wheel over silos", "Select previous / next silo"),
        ("Wheel over the tab bar", "Switch project"),
        ("Ctrl+Wheel in the editor", "Zoom the editor font"),
        ("Middle-click a silo", "Move it to the trash (text + files land in data/files/_trash)"),
        ("Ctrl+Middle-click a line in the editor", "Delete that whole line"),
        ("Hover a silo",
         "&#9989; tick, &#128193; files, &#128204; pin and &#128229; archive buttons appear"),
        ("Click &#9989; on a silo", "Mark it done — the tick stays until clicked again"),
        ("Click &#9112; on a ``` code fence", "Copy that code block to the clipboard"),
        ("Click &#9662; on a header / fence",
         "Fold (collapse) the section; right-click editor &rarr; Expand All Folds"),
        ("Click &#9636; on a silo header",
         "The Pack control on a silo header: click reuses or bundles into one "
         "portable ZIP &amp; copies it, Shift+click chooses what goes in, "
         "Ctrl+click forces repack, Ctrl+Shift+click copies last bundle, "
         "Alt+click opens last bundle folder, right-click opens actions."),
        ("Alt+drop files on the Files panel", "Add .url links instead of copies"),
        ("Drag files over the editor",
         "A grid of drop zones appear: insert as text, "
         "link in text, copy to silo Files, or link in silo Files"),
        ("In the Files panel",
         "Del delete &middot; F2 rename &middot; Enter open &middot; "
         "Ctrl+Shift+C copy path &middot; Ctrl+N new folder &middot; Ctrl+V clipboard&rarr;file"),
        ("Right-click a silo", "Transfer to project, replace from, move to bottom&hellip;"),
        ("Ctrl+drop a silo onto another",
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
        f"<li><b>{tr('Projects', lang)}</b> — {tr('up to 100 tabs, each with its own silos, snippets, archive', lang)}</li>"
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
        f"<li><b>{tr('Clock &amp; Timer', lang)}</b> &mdash; {tr('date + time with seconds, day word, optional mini analog clock, and a Pomodoro-style timer with snooze', lang)}</li>"
        f"<li><b>{tr('Scale', lang)}</b> &mdash; {tr('50&ndash;150% whole-UI scaling with readable minimums', lang)}</li>"
        f"<li><b>{tr('Sounds', lang)}</b> &mdash; {tr('optional UI clicks and typewriter effect', lang)}</li>"
        f"<li><b>{tr('Data', lang)}</b> &mdash; {tr('SQLite next to the app; daily Markdown backups in Documents; crash log next to the EXE', lang)}</li>"
        "</ul>"
    )
    # T-1238-D.2 -- Problip and the Audio Hub in plain words.  Product help
    # only: nothing about Android billing, premium tiers or store listings.
    audio = (
        "<ul style='margin:2px 0 2px 14px;'>"
        f"<li><b>{tr('Problip', lang)}</b> &mdash; "
        f"{tr('a short cue at your chosen interval so a long writing session keeps its rhythm. Settings has its own Problip tab: Start, Stop and Test.', lang)}</li>"
        f"<li><b>{tr('Interval', lang)}</b> &mdash; "
        f"{tr('Random 4-7 s, a fixed 5/10/15/20/30 s, Pulse (alternating short and long waits) or Manual with your own FROM and TO.', lang)}</li>"
        f"<li><b>{tr('Sound pool', lang)}</b> &mdash; "
        f"{tr('six bundled sounds; tick as many as you like and each cue picks one at random. The last ticked sound cannot be unticked, and an unavailable file is marked instead of silently swapped.', lang)}</li>"
        f"<li><b>{tr('Statistics', lang)}</b> &mdash; "
        f"{tr('today, this week, this month and the running total. Only a cue that really played is counted. Reaching 100,000 is permanent.', lang)}</li>"
        f"<li><b>{tr('Playback modes', lang)}</b> &mdash; "
        f"{tr('Overlay lets different sounds play together, Stack plays them one after another in order, Replace lets the newest sound stop the current one. Each event can override the global choice, and a scheduled Problip cue can also Skip while busy so it never talks over an alarm.', lang)}</li>"
        f"<li><b>{tr('Presets', lang)}</b> &mdash; "
        f"{tr('whole sound sets you can apply, save, rename, export and import. Imported files are copied into your own managed library, so the original folder is never needed again.', lang)}</li>"
        f"<li><b>{tr('Voice countdown', lang)}</b> &mdash; "
        f"{tr('announces 1 hour, 30, 15, 10 and 5 minutes before the nearest timer or the nearest known AI-limit reset. It never announces a moment that has already passed and never repeats one after a restart.', lang)}</li>"
        f"<li><b>{tr('GoldSrc / AMX import', lang)}</b> &mdash; "
        f"{tr('point it at ONE folder you already own; recognised VOX, FVOX, G-Man and AMX clips are copied into your managed library. Nothing is downloaded and nothing is bundled with the app.', lang)}</li>"
        f"<li><b>{tr('Ambience', lang)}</b> &mdash; "
        f"{tr('long-running background layers with their own volume and fades, triggered always, inside a time window, on a weekday, or by the weather.', lang)}</li>"
        f"<li><b>{tr('Weather', lang)}</b> &mdash; "
        f"{tr('off until you switch it on and type a place with its latitude and longitude. Nothing else is sent, nothing is located automatically, and a failed lookup simply leaves the condition unknown.', lang)}</li>"
        f"<li><b>{tr('STOP ALL SOUND', lang)}</b> &mdash; "
        f"{tr('one click silences everything at once: clicks, alarms, voice phrases, Problip, previews, ambience and every queue. New sounds still work afterwards.', lang)}</li>"
        f"<li><b>{tr('When sounds collide', lang)}</b> &mdash; "
        f"{tr('rapid repeats of the same sound are folded together instead of piling up, ambience is never cut short by an ordinary Replace, and only STOP ALL SOUND or Stop ambience silences a background layer.', lang)}</li>"
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
        f"<h3 style='margin:10px 0 2px 0;'>{tr('Problip and the Audio Hub', lang)}</h3>"
        f"{audio}"
    )


class HelpDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self._main_win = main_win
        self._lang = getattr(main_win, '_current_lang', 'EN')
        self.setWindowTitle(tr("FastPrompter — Help", self._lang))
        self.setModal(False)
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(build_help_html(main_win.data, self._lang))
        layout.addWidget(browser)
        
        btn_layout = QHBoxLayout()
        
        support_btn = QPushButton(tr("🤍 Support developer", self._lang), self)
        support_btn.setStyleSheet("background-color: #2b2b2b; color: #ffdd00; font-weight: bold; border-radius: 4px; padding: 4px 8px;")
        support_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        support_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/vacuum34")))
        btn_layout.addWidget(support_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # A door straight from Help into the Shortcut settings: the help sheet
        # lists every hotkey, so the place to rebind them belongs one click away
        # instead of hunting the settings cog.
        shortcut_btn = QPushButton(tr("Shortcut settings", self._lang), self)
        shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shortcut_btn.clicked.connect(self._open_shortcut_settings)
        btn_layout.addWidget(shortcut_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        btn_layout.addStretch()

        btn = QPushButton(tr("Close", self._lang), self)
        btn.clicked.connect(self.close)
        btn_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        
        layout.addLayout(btn_layout)

    def _open_shortcut_settings(self):
        opener = getattr(self._main_win, "open_hotkey_settings", None)
        if callable(opener):
            opener()
