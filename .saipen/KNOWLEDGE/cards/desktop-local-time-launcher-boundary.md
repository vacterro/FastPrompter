<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: launcher,time
trigger: starting FastPrompter from an external desktop launcher
status: active
evidence: architecture.md
supersedes: none

# The desktop launcher owns the local-time environment

`FastPrompter.pyw` removes inherited `TZ` before importing application code so Python follows the Windows local timezone instead of a launcher-injected UTC override.

Why:
Python consults `TZ` on first clock use and can cache it. A launcher-provided `TZ=UTC` otherwise moves every topbar and timer three hours behind, while fixing only the displayed label would leave scheduling logic on a different clock.
