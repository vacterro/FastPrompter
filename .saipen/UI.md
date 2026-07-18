# asp UI — Win95 Dark Golden Design Spec

## 1. Palette

| Role | Color | Hex |
|------|-------|-----|
| Window background | Dark brown-black | `#1a1a10` |
| Button face | Warm golden-brown | `#c8a84e` |
| Button highlight | Light gold | `#e8d48a` |
| Button shadow | Dark brown | `#5a4a20` |
| Text primary | Warm golden | `#e8d48a` |
| Text dimmed | Muted gold | `#8a7a40` |
| Surface raised | Raised bevel (lighter) | `#2a2a18` |
| Surface sunken | Sunken bevel (darker) | `#121208` |
| Selection | Amber | `#d4a030` |
| Accent | Golden | `#d4a84e` |
| Border | Dark brown | `#3a2a10` |

## 2. Typography

- **Primary font**: Verdana (no antialiasing — set via `NoAntialias` style strategy)
- **Base size**: 11px (unless overridden by user)
- **Bold**: Weight 700 for headers, buttons
- **No subpixel antialiasing** — use `NoSubpixelAntialias` flag
- **Header font**: same as primary, bold + underline for `#` markdown

## 3. Bevels & Borders

Win95-style 3D bevels:
- **Raised**: light top-left, dark bottom-right
- **Sunken**: dark top-left, light bottom-right
- **Button**: default raised, pressed = sunken
- **Checkbox**: sunken well, gold checkmark
- **Frame**: `QFrame::Shape.VLine` / `HLine` with `Sunken` shadow

## 4. Button Dimensions

| Context | Size | Notes |
|---------|------|-------|
| Formatting squares (BIUSH) | 18×18 (dense), 24×24 (normal) | `apply_button_size` |
| Action buttons (NEW/Save/Copy) | 24px height, width = clip_safe_width | Text clipped to fit |
| Silo buttons | Dynamic, min 14px height | From silo_rows layout |
| Small buttons (📌 #) | 20×20 | Pin, line-nums |
| Extra small (tab +/-) | 18×18 | When dense |

## 5. Density Tiers

| Tier | Width | Behavior |
|------|-------|----------|
| Normal | ≥1280px | Full header, all buttons |
| Dense | 700–1279px | Short labels (CF→✕, Line→─), tight spacing |
| Ultra | <700px | Only tabs/NEW/Save/clock/counter/⚙ survive |

## 6. Header Layout (left-to-right)

☰ [tabs] [NEW] [Save] [Home] [End] ── [B I U S H] [CF] [Line] [-→•] [Copy] [Clear] ── [🕒] [DD.MM - HH:MM] [📌] [#] [│] [177] [⚙] [❓]

In dense: formatting group and rare buttons collapse. In ultra: only essentials.

## 7. Sidebar Layout

```
[🗑️]  [⌕] [📥] [📦] [📁]
[Search...]
[▲]
[snippets (F1-F10)]
[▼]
[Archive section]
[▲]
[silos]
[▼]
```

## 8. Silo Row

`[✅] [text] [📁N] │ [177]`

- Ticks: hover-only, toggleable in Settings
- 📁N: shows file count; empty = 📁 on hover
- │ separator before line counter
- Counter: bold, shows line count only (not file count — that's 📁)
- Tint: color-coded by recency of last edit (warm=recent, dim=stale)

## 9. Scrollbar (Win95)

- Arrow buttons at top/bottom
- Thumb: sunken bevel, proportional to content size
- No smooth scrolling — page-based (Qt default for lists)

## 10. Settings Panel

Toggled by ⚙. Groups: Window / Editor / Data & Appearance.
QGridLayout, 2 columns, equal stretch between groups.
