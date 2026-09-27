<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: usage-limits,time
trigger: parsing or rendering provider quota reset timestamps
status: active
evidence: architecture.md
supersedes: none

# Quota reset timestamps cross provider boundaries as instants

Every provider reset becomes a numeric instant before entering `UsageWindow`; local wall-time strings must not be reattached to the current machine offset, and named IANA zones must survive until `zoneinfo` resolves them. UI code converts that final epoch to the operator's local timezone.

Why:
A reset error silently changes expiry, countdown, gating, and notifications. DST, travel, SSH hosts, omitted years, milliseconds, and ISO spellings have each produced user-visible drift; the epoch boundary plus bundled timezone data removes that whole class instead of patching one display.
