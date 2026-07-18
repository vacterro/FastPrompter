# Phase: FIX

## Purpose
Implement changes — edit files, add tests, iterate until correct.

## Entry condition
- Plan accepted or task is straightforward
- Ticket(s) on BOARD.md in TODO or INPROGRESS status

## Exit condition
- All changes implemented and reviewed
- Code compiles/runs without errors

## Behaviors
- Write todos for multi-step changes
- Prefer str_replace over write_file for targeted edits
- Reuse existing helpers and patterns
- Test the specific area before widening scope
- Remove dead code (unused imports, orphaned functions)
- Add imports as needed
- Spawn reviewer after implementation

## Constraints
- Do not change behavior more than necessary
- Assume every line has a purpose
- Follow existing project conventions strictly
