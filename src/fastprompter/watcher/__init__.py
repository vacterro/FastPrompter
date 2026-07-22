"""Prompt queue watcher package.

Manages the lifecycle of external AI agent CLIs: launch, send prompts,
detect completion, and trigger the next queued prompt.

Sub-packages
────────────
adapters    — agent-specific implementations (Claude, Freebuff, etc.)
"""
