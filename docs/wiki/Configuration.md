# FastPrompter Configuration & Settings Reference

## Database Settings Schema
Settings stored in SQLite database (`data/fastprompter.db` or `data/fastprompter_p<ID>.db`) within the `settings` table as key-value text pairs.

### Settings Keys Reference

| Setting Key | Type | Default | Description |
|---|---|---|---|
| `theme` | string | `"Default"` | Active theme (`Default`, `Amber`, `OLED`, `Win95`, `Rose`, `Custom`) |
| `font_family` | string | `"Verdana"` | Editor font family (resolves to `_m1` bitmap variant if installed) |
| `font_size` | integer | `11` | Editor font size in points |
| `ui_scale` | float | `"0.5"` | Overall UI scaling (0.5 to 1.5) |
| `button_scale` | float | `"1.0"` | Silo & toolbar button size multiplier |
| `global_hotkey` | string | `"Alt+X"` | Show/hide window hotkey |
| `pie_menu_hotkey` | string | `"Shift+Alt+X"` | Pie menu hotkey |
| `lock_window_hotkey` | string | `"Alt+S"` | Window position lock toggle |
| `always_on_top_hotkey` | string | `"Alt+E"` | Always-on-Top toggle |
| `close_on_focus_loss` | boolean | `"True"` | Auto-hide on focus loss |
| `sound_ui` | boolean | `"False"` | UI click sound effects |
| `sound_typewriter` | boolean | `"False"` | Typewriter key sounds |
| `sound_volume` | integer | `"5"` | Sound volume (0 to 10) |
| `portable_backup_enabled` | boolean | `"True"` | Auto .bak on startup |
| `language` | string | `"EN"` | Interface language (23 options) |
| `sidebar_right` | boolean | `"False"` | Sidebar on right side |
| `code_auto_gutter` | boolean | `"False"` | Auto line numbers in code blocks |
| `code_monospace` | boolean | `"True"` | Monospace font in code blocks (False = use editor font) |
| `hr_line` | boolean | `"False"` | Render `---` as visual line instead of text |
| `ctrl_e_center` | boolean | `"False"` | Center-align headers (Ctrl+E) |
| `auto_bullet` | boolean | `"False"` | Auto-convert dashes to bullets |
| `custom_cursors` | boolean | `"False"` | Retro cursor theme overlay |
| `hover_line_color` | string | `"auto"` | Line highlight color (auto = theme accent) |
| `watcher_skill` | string | `""` | Default skill for watcher queue items |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | Category tab order |
| `timers` | JSON | `[]` | Saved countdown/timer definitions |
| `productivity_timer` | JSON | — | Pomodoro timer state |
| `watcher_queues` | JSON | `{}` | Per-silo watcher prompt queues |
| `toolbar_order` | string | — | Custom toolbar button order tokens |
| `snippets_hidden` | boolean | `"False"` | Snippets panel visibility |
| `date_seconds` | boolean | `"True"` | Show seconds in clock |
| `date_daypart` | boolean | `"True"` | Show Morning/Day/Evening/Night |
| `date_text_month` | boolean | `"False"` | Use text month (Jan/Feb) |
| `date_ampm` | boolean | `"False"` | 12h AM/PM format |
| `date_emoji` | boolean | `"False"` | Emoji daypart (🌅/☀️/🌇/🌙) |

---

## File System & Storage Directory Structure

All user data is stored in a self-contained `data/` directory adjacent to the executable:

```
data/
├── fastprompter.db             # Main SQLite database (default profile)
├── fastprompter.db.bak         # Startup backup snapshot
├── fastprompter_p2.db          # Profile 2 database
├── fastprompter_p2.db.bak      # Profile 2 backup
├── silo_files/                 # File Container attachments
│   ├── Code/                   # Category folder
│   │   ├── 0/                  # Silo slot 0 directory
│   │   └── 1/                  # Silo slot 1 directory
│   └── Text/
├── _trash/                     # Soft-deleted silos and files
│   └── 2026-07-22_153022_Silo0/# Timestamped trash
└── custom_theme.json           # User-defined color palette
```

Daily Markdown Mirror: `%USERPROFILE%\Documents\.fastprompter\`

---

## Custom Themes & Color Editing

When `theme` is set to `"Custom"`, colors are read from `custom_theme.json` or state overrides.

### Supported Color Tokens
- `bg_main`: Primary window background
- `bg_editor`: Editor canvas background
- `fg_text`: Primary text color
- `border`: Window border and divider lines
- `accent`: Active selection, focus ring, pin highlight
- `header_bg`: Header bar background

---

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
