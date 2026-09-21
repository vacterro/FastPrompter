# FastPrompter — SAIPEN protocol bootstrapping

This project is run under the SAIPEN agent protocol. Every chat in this repo must
recognize SAIPEN commands and shortcuts **from the very first message**, without
waiting for a skill to be invoked by name.

## SAIPEN home

- Skill home: `C:\Users\vac34\.agents\skills\saipen\` — authoritative documents
  are `BOOT.md` (cold-start kernel), `CORE.md` (constitution), `COMMANDS.md`
  (command semantics), `INDEX.md` (document map).
- Project memory: `<repo root>/.saipen/` — `STATE.md` → `BOARD.md` → `LOG.md`
  tail is the canonical boot order; execute the `next_action`.

## Recognizing SAIPEN input

A user message is a SAIPEN command when it is one of the shortcuts below
(Latin or its Cyrillic twin), a `saipen ...` phrase, or `/saipen ...`. Do not
treat these as stray input, typos, or abbreviations.

| Input | Means | Input | Means |
|-------|-------|-------|-------|
| `gg`  | saipen goal | `qq`  | saipen prepare saiwiki |
| `hh`  | saipen hunt | `qqq` | saipen collect saiwiki |
| `ff`  | saipen focus | `ee`  | saipen prepare saitranslate |
| `xx`  | saipen cut | `eee` | saipen collect saitranslate |
| `vv`  | saipen build | `pp`  | saipen sub spawn saipython |
| `zz`  | saipen undo | `tt`  | saipen test |
| `cc`  | saipen continue | `sc`  | saipen crew |
| `ccc` | saipen continue (converge) | `ss`  | saipen stop |
| `dd`  | saipen plan | `sss` | saipen status |
| `aa`  | saipen markhunt | `saipen` | boot saipen (read BOOT.md) |

## Executing a SAIPEN command

1. If this thread does not already hold the SAIPEN protocol in context, first
   read the skill home `BOOT.md` (it chains to `STYLE.md`, `STATE.md`,
   `BOARD.md`, `LOG.md`, phases per current phase).
2. Map the shortcut via `COMMANDS.md` and act on the project `.saipen/` state —
   do not ask the user to re-invoke the skill or spell out the command.
3. If the shortcut needs a payload (`gg <goal>`, `dd <items>`, ...) and none was
   given, ask once in reply-language, otherwise proceed per the rules.

Keep this file lean; protocol details live in the SAIPEN skill home, not here.
