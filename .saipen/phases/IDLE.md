# Phase: IDLE

## Purpose
Awaiting user direction. No active tickets. System ready.

## Entry condition
- All DONE items verified
- All tests green
- No blocker

## Exit condition
- User submits a new request → transition to HUNT or PLAN

## Behaviors
- Report current state (phase, last handoff, test status)
- Accept new direction
- No autonomous work
