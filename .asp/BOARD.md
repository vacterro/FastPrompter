# ASP Board

## Wave v0.5.3 (17.07.26)

| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-101 | DONE | claude-fable | - | BUG: Ctrl+E header edit re-slugs title -> new files folder, old buried (data/files/code/) |
| T-102 | DONE | claude-fable | - | BUG: container Delete button dead; + Ctrl+Shift+C copy path, rich shortcuts in panel |
| T-103 | DONE | claude-fable | - | BUG: theme change garbles/truncates toolbar button texts (screens 0420xx) |
| T-104 | DONE | claude-fable | - | BUG: deleting silo can hide snippet (screen 041723) |
| T-105 | DONE | claude-fable | - | BUG: header date refresh glyph may disappear — investigate |
| T-106 | DONE | claude-fable | - | BUG: Normal Window toggle flashbang, no immediate title bar update |
| T-110 | DONE | claude-fable | - | Top bar right: pin (always-on-top), line-numbers toggle, separator files-counter/line-counter |
| T-111 | DONE | claude-fable | - | Layout: Home/End left; settings+files right group; snippet +/- separator; arrows toggleable OFF |
| T-112 | TODO | - | - | Silo hover: tickbox toggle left of number |
| T-113 | DONE | claude-fable | - | Silo: middle-click -> trash; context menu Move to Trash |
| T-114 | DONE | claude-fable | T-113 | Context menus rethink + icons (silo, snippet) |
| T-115 | DONE | claude-fable | - | Header format template: {text} {time} {state}, user-editable, no hardcoded bold |
| T-116 | DONE | claude-fable | - | Mini analog clock near date (toggleable, hour+minute hands) |
| T-117 | DONE | claude-fable | - | Hotkeys: defaults Alt+E top / Alt+S lock / Alt+A hideout; all bindable; tooltips show them |
| T-118 | TODO | - | T-102 | Container: New Folder, richer shortcuts |
| T-119 | TODO | - | - | Drop overlay effect for text files (screen 044916); no-text drops -> container auto |
| T-120 | TODO | - | - | Folder Template editor (ref NEW_PROJ.CMD) — create templated folder trees in container |
| T-121 | TODO | - | - | Settings UI compact redesign (screen 044432) |
| T-122 | TODO | - | - | Search reliability pass |
| T-123 | TODO | - | - | Silo hierarchy: 1-level children, indent, collapse, files merge on combine (BIG) |
| T-124 | TODO | - | - | Help + README refresh; dead code sweep |
| T-125 | TODO | - | all-bugs | Ship v0.5.3 |

## DONE (previous waves)

| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-001 | DONE | Antigravity | - | Fix bug: FileContainerPanel._watcher AttributeError |
| T-002 | DONE | Antigravity | - | Fix bug: text clipping in toolbar buttons |
| T-003 | DONE | Antigravity | - | Add toggleable date format option (17.07 vs 17 Jul) |
| T-004 | DONE | Antigravity | - | Fix/Update tests for Ctrl+W divider and Ctrl+E timestamp formatting |
| T-005 | DONE | Antigravity | T-004 | Compact top bar UI (960px with Seconds + Day Word) |
| T-006 | DONE | Antigravity | - | Fix test_inline_timestamp_refresh_glyph regex |
| T-007 | DONE | Antigravity | T-004 | Smoke test stabilization (65 pass) |
