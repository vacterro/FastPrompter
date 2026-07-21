"""Adapters: an agent described in config rather than in code.

Adding an agent means adding a block to adapters.toml. Nothing here imports
anything agent-specific, so a CLI nobody has heard of is supported the
moment somebody writes down how to tell when it is idle.

Errors are isolated per entry. One malformed adapter is disabled and its
reason surfaced; it never takes the others, or the app, down with it.
"""

from __future__ import annotations

import os
import re
import tomllib

from fastprompter.core.watcher.probes import build as build_probe

DEFAULT_LIMITS = {
    "min_gap_ms": 4000,
    "max_sends": 25,
    "dry_run_new": True,
    # The feature exists to drain a queue while the user works elsewhere.
    # Anything that interrupts them defeats it.
    "confirm_first": False,
    "allow_focus_steal": False,
    "restore_clipboard_ms": 400,
}


class Adapter:
    """One agent: how to tell it is idle, and how to talk to it."""

    def __init__(self, name, probes=(), enabled=True, settle_ms=2500,
                 submit="enter", multiline="join",
                 skill_format="/{skill} {text}", blocker_pattern="",
                 problems=()):
        self.name = name or "unnamed"
        self.probes = list(probes)
        self.enabled = bool(enabled)
        try:
            self.settle_ms = max(0, int(settle_ms))
        except (TypeError, ValueError):
            self.settle_ms = 2500
        self.submit = submit or "enter"
        self.multiline = multiline or "join"
        # absent means the agent has no skills at all - the palette hides
        # them for it, and an item carrying one is skipped rather than sent
        # stripped of it
        self.skill_format = skill_format or None
        self.problems = list(problems)

        self._blocker = None
        if blocker_pattern:
            try:
                self._blocker = re.compile(blocker_pattern)
            except re.error as exc:
                self.problems.append(f"bad blocker_pattern: {exc}")

    # ---- readiness ----------------------------------------------------
    def unsupported_probes(self):
        """Which probes cannot run, and why.

        Asks `supported()`, never `poll()`. Polling to answer a readiness
        question would stamp the probe's quiet window at whatever clock was
        passed, and the next real poll would then read as idle straight away.
        """
        out = []
        for probe in self.probes:
            try:
                ok, reason = probe.supported()
            except Exception as exc:
                out.append(f"probe failed: {exc}")
                continue
            if not ok:
                out.append(reason or getattr(probe, "kind", "probe"))
        return out

    def supported(self):
        """Can this adapter actually watch anything?

        An adapter with no probes, or with one that cannot run, is not
        usable. Reporting it as ready would mean arming a watcher that can
        never tell whether the agent is busy - and one that cannot tell must
        never be the thing that releases a prompt.
        """
        if not self.probes:
            return False, "no probes configured"
        missing = self.unsupported_probes()
        if missing:
            return False, "; ".join(missing)
        if self.problems:
            return False, "; ".join(self.problems)
        return True, "ready"

    def blocked(self, text):
        """Does the target's visible text say now is a bad moment?

        A permission prompt is silent, so the probes would call it idle -
        this is the override that stops a send landing on one.
        """
        if self._blocker is None or not text:
            return False
        return bool(self._blocker.search(text))

    def __repr__(self):
        return f"Adapter({self.name!r}, {len(self.probes)} probes)"


def _adapter_from(entry, project=None):
    """One [[agent]] block. Raises only on things that make it meaningless."""
    if not isinstance(entry, dict):
        raise ValueError("not a table")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("missing a name")

    probes, problems = [], []
    for spec in entry.get("probe") or ():
        try:
            probes.append(build_probe(spec, project=project))
        except Exception as exc:
            problems.append(f"bad probe: {exc}")

    return Adapter(
        name=name.strip(),
        probes=probes,
        enabled=entry.get("enabled", True),
        settle_ms=entry.get("settle_ms", 2500),
        submit=entry.get("submit", "enter"),
        multiline=entry.get("multiline", "join"),
        skill_format=entry.get("skill_format"),
        blocker_pattern=entry.get("blocker_pattern", ""),
        problems=problems,
    )


def parse_adapters(text, project=None):
    """(adapters, limits, errors) from TOML text.

    A single broken entry costs that entry and nothing else — the whole
    point of describing agents in config is that a typo in one cannot take
    the working ones with it.
    """
    errors = []
    try:
        data = tomllib.loads(text or "")
    except Exception as exc:
        return [], dict(DEFAULT_LIMITS), [f"could not parse the config: {exc}"]

    adapters = []
    for index, entry in enumerate(data.get("agent") or (), start=1):
        try:
            adapters.append(_adapter_from(entry, project=project))
        except Exception as exc:
            label = entry.get("name") if isinstance(entry, dict) else f"#{index}"
            errors.append(f"{label}: {exc}")

    limits = dict(DEFAULT_LIMITS)
    for key, value in (data.get("limits") or {}).items():
        if key in limits:
            limits[key] = value
        else:
            errors.append(f"unknown limit {key!r}")
    return adapters, limits, errors


def load_adapters(path=None, fallback=None, project=None):
    """Read the user's adapters.toml, falling back to the shipped example."""
    for candidate in (path, fallback):
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            return [], dict(DEFAULT_LIMITS), [f"could not read {candidate}: {exc}"]
        adapters, limits, errors = parse_adapters(text, project=project)
        return adapters, limits, errors
    return [], dict(DEFAULT_LIMITS), ["no adapters.toml found"]


def usable_adapters(adapters):
    """Only the ones that are enabled AND can actually watch something."""
    out = []
    for adapter in adapters:
        if not adapter.enabled:
            continue
        ok, _reason = adapter.supported()
        if ok:
            out.append(adapter)
    return out


def describe(adapters):
    """[(name, ready, reason)] — what the UI shows, including the refusals.

    Disabled and unsupported adapters are listed with their reason rather
    than hidden: "my agent is not in the list" is a question the user should
    be able to answer without reading the config.
    """
    rows = []
    for adapter in adapters:
        if not adapter.enabled:
            rows.append((adapter.name, False, "disabled in the config"))
            continue
        ok, reason = adapter.supported()
        rows.append((adapter.name, ok, reason))
    return rows
