# FastPrompter Configuration & Settings Reference

## Database Settings Schema
Settings are stored in the SQLite database (`data/fastprompter.db` or `data/fastprompter_p<ID>.db`) within the `settings` table as key-value text pairs.

### Settings Keys Reference

| Setting Key | Type | Default | Description |
|---|---|---|---|
| `theme` | string | `"Default"` | Active visual theme (`"Default"`, `"Amber"`, `"OLED"`, `"Win95"`, `"Rose"`, `"Custom"`) |
| `font_size` | integer | `11` | Primary editor font size in points |
| `ui_scale` | float | `"1.0"` | Overall UI scaling factor (0.5 to 1.5) |
| `button_scale` | float | `"1.0"` | Silo & toolbar button size multiplier |
| `global_hotkey` | string | `"Alt+X"` | Primary hotkey to show/hide application window |
| `pie_menu_hotkey` | string | `"Shift+Alt+X"` | Hotkey to trigger radial pie menu |
| `lock_window_hotkey` | string | `"Alt+S"` | Hotkey to toggle window position lock |
| `always_on_top_hotkey` | string | `"Alt+E"` | Hotkey to toggle Always-On-Top window mode |
| `close_on_focus_loss` | boolean | `"True"` | Automatically hide window when focus is lost |
| `ctrl_c_closes` | boolean | `"True"` | Close/hide window after pressing `Ctrl+C` in snippet mode |
| `sound_ui` | boolean | `"False"` | Enable UI button click sound effects |
| `sound_typewriter` | boolean | `"False"` | Enable typewriter key sound effects |
| `sound_volume` | integer | `"5"` | Sound volume level (0 to 10) |
| `portable_backup_enabled` | boolean | `"True"` | Automatic creation of `.bak` database file on startup |
| `language` | string | `"EN"` | Interface language (`EN`, `RU`, `UK`, `DE`, `FR`, `ES`, `IT`, `PT`, `NL`, `PL`, `SV`, `DA`, `FI`, `NO`, `JA`, `ZH`, `KO`, `TH`, `VI`, `AR`, `HE`, `ET`, `DED`) |
| `sidebar_right` | boolean | `"False"` | Position silo sidebar on right side of editor |
| `code_auto_gutter` | boolean | `"False"` | Automatically display line numbers in editor code blocks |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | Custom order of project category tabs |

---

## File System & Storage Directory Structure

FastPrompter stores all user data in a self-contained `data/` directory adjacent to the executable, ensuring 100% portable execution.

```
data/
├── fastprompter.db             # Main SQLite database (Default profile)
├── fastprompter.db.bak         # Startup backup SQLite database
├── fastprompter_p2.db          # Profile 2 SQLite database
├── silo_files/                 # File Container attachments
│   ├── Code/                   # Category folder
│   │   ├── 0/                  # Silo slot 0 attachment directory
│   │   └── 1/                  # Silo slot 1 attachment directory
│   └── Text/
├── _trash/                     # Soft-deleted silos and files
│   └── 2026-07-22_153022_Silo0/# Timestamped trash archive
└── custom_theme.json           # User-defined custom color palette (if enabled)
```

---

## Custom Themes & Color Editing
When `theme` is set to `"Custom"`, FastPrompter reads color preferences from `custom_theme.json` or state overrides.

### Supported Theme Color Tokens
- `bg_main`: Primary window and panel background color
- `bg_editor`: Editor canvas background color
- `fg_text`: Primary text color
- `border`: Window border and divider line color
- `accent`: Active selection, focus ring, and pin highlight color
- `header_bg`: Header bar and title background color
