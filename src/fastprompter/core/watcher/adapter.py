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
import string
import tomllib

from fastprompter.core.watcher.probes import build as build_probe

DEFAULT_LIMITS = {
    "min_gap_ms": 4000,
    "max_sends": 25,
    "dry_run_new": True,
}

# The only fields skill_format may interpolate. `compose()` in queue.py formats
# with exactly these keyword names, so any other field, or malformed braces,
# can only fail there at runtime — after the adapter was already advertised as
# ready and armed. Validate at parse/readiness instead (CORE-011).
_SKILL_FORMAT_FIELDS = ("skill", "text")

# The transports a sender can actually be built for (watcher_mixin reads
# `transport == "cdp"` and posts for everything else, so anything but these
# two would silently arm the post sender), and the multiline policies
# sender._flatten implements - an unknown one falls into `join` without a
# word (CORE-011).
_TRANSPORTS = ("post", "cdp")
_MULTILINE = ("join", "refuse", "bracketed")


def validate_skill_format(fmt):
    """(ok, reason) — does ``skill_format`` format with ``skill``/``text`` only?

    An empty/None format is the intentional "this adapter has no skills" state
    and is always valid. Anything else must parse as a Python format string
    whose only field names are ``skill`` and ``text``: an unknown field raises
    ``KeyError`` at ``QueueItem.compose`` and an unmatched brace raises
    ``ValueError``, both of which would stop the watcher the first time a
    skill-bearing item reached this adapter.
    """
    if not fmt:
        return True, ""
    try:
        for _literal, field_name, _spec, _conv in string.Formatter().parse(fmt):
            if field_name is None:
                continue
            name = field_name.split("[", 1)[0].split(".", 1)[0]
            if name not in _SKILL_FORMAT_FIELDS:
                return False, f"unknown field {{{field_name}}} in skill_format"
        # authoritative: catches unmatched braces and confirms it formats
        fmt.format(skill="x", text="y")
    except Exception as exc:
        return False, f"malformed skill_format: {exc}"
    return True, ""


def validate_submit_key(submit, transport):
    """(ok, reason) — can this transport actually press this key?

    An invalid submit key used to surface only at send time: PostLayer.press
    returns False for a key it cannot map, and CdpSender raises AFTER the
    composer already holds the inserted text. Readiness is the place to
    catch it (CORE-011). Both key tables are read from the modules that do
    the pressing, so this cannot drift from what the senders accept.
    """
    from fastprompter.core.watcher.cdp import _KEYS
    from fastprompter.core.watcher.win32 import VK

    if not isinstance(submit, str) or not submit.strip():
        return False, f"submit must be a key name, got {submit!r}"
    key = submit.strip().lower()
    if transport == "cdp":
        if key in _KEYS:
            return True, ""
        return False, f"the cdp transport cannot press submit {submit!r}"
    # The post layer maps the final part through VK, or takes a single
    # character; every modifier must be a VK name.
    parts = [p.strip() for p in key.split("+") if p.strip()]
    if not parts:
        return False, f"submit must be a key name, got {submit!r}"
    mods, main = parts[:-1], parts[-1]
    if main not in VK and len(main) != 1:
        return False, f"unknown submit key {submit!r}"
    if any(mod not in VK for mod in mods):
        return False, f"unknown submit key {submit!r}"
    return True, ""


def _str_field(label, value, problems):
    """The value when it is a string, else "" — a non-string is a problem.

    These fields reach os.path (the port file) or a JS selector; an int in
    cdp_port_file used to get as far as os.path.expandvars inside a live
    tick before raising TypeError (CORE-011).
    """
    if isinstance(value, str):
        return value
    if value not in (None, ""):
        problems.append(f"{label} must be a string, got {value!r}")
    return ""


class Adapter:
    """One agent: how to tell it is idle, and how to talk to it."""

    def __init__(self, name, probes=(), enabled=True, settle_ms=2500,
                 submit="enter", multiline="join",
                 skill_format="/{skill} {text}", blocker_pattern="",
                 transport="", cdp_port=0, cdp_title="",
                 cdp_port_file="", cdp_selector="", problems=()):
        self.name = name or "unnamed"
        self.probes = list(probes)
        self.enabled = bool(enabled)
        try:
            self.settle_ms = max(0, int(settle_ms))
        except (TypeError, ValueError):
            self.settle_ms = 2500
        problems = list(problems)
        # CORE-011: readiness has to vouch for everything the sender will
        # run. A config that only fails at send time — an unknown transport
        # that quietly becomes post, a submit key the transport cannot
        # press, a multiline policy that silently becomes join — is a config
        # that can type into a live composer and only then discover it
        # cannot finish the send. Each bad value is a problem on THIS
        # adapter: never an exception, never a silent default.
        if not isinstance(submit, str):
            if submit not in (None, ""):
                problems.append(f"submit must be a string, got {submit!r}")
            submit = ""
        self.submit = (submit.strip() or "enter").lower()
        if not isinstance(multiline, str):
            if multiline not in (None, ""):
                problems.append(
                    f"multiline must be a string, got {multiline!r}")
            multiline = ""
        self.multiline = (multiline.strip() or "join").lower()
        if self.multiline not in _MULTILINE:
            problems.append(f"unknown multiline {multiline.strip()!r} "
                            f"(expected {', '.join(_MULTILINE)})")
        # absent means the agent has no skills at all - the palette hides
        # them for it, and an item carrying one is skipped rather than sent
        # stripped of it
        if skill_format not in (None, "") and not isinstance(skill_format,
                                                             str):
            problems.append(
                f"skill_format must be a string, got {skill_format!r}")
            skill_format = ""
        self.skill_format = skill_format or None
        # How to talk to it. Posting Win32 messages does nothing to a
        # Chromium window, so this is per agent rather than one mechanism
        # for all of them - see PLAN.md section 10b.
        if not isinstance(transport, str):
            if transport not in (None, ""):
                problems.append(
                    f"transport must be a string, got {transport!r}")
            transport = ""
        self.transport = (transport.strip() or "post").lower()
        if self.transport not in _TRANSPORTS:
            problems.append(f"unknown transport {transport.strip()!r} "
                            f"(expected {' or '.join(_TRANSPORTS)})")
        else:
            ok_key, key_reason = validate_submit_key(self.submit,
                                                     self.transport)
            if not ok_key:
                problems.append(key_reason)
        try:
            self.cdp_port = int(cdp_port or 0)
        except (TypeError, ValueError):
            self.cdp_port = 0
        self.cdp_title = _str_field("cdp_title", cdp_title, problems)
        # Chromium picks a fresh debug port every launch, so a fixed one
        # works until the app restarts. The port file is where it records
        # the live one.
        self.cdp_port_file = _str_field("cdp_port_file", cdp_port_file,
                                        problems)
        # Which field on the page is the composer. Left empty the
        # sender uses its own default; named when a page has
        # several and the guess would pick the wrong one.
        self.cdp_selector = _str_field("cdp_selector", cdp_selector, problems)
        if self.transport == "cdp" and not (self.cdp_port or self.cdp_port_file):
            problems.append("cdp transport needs a cdp_port or a cdp_port_file")
        # A malformed skill_format is a per-entry problem, not a runtime surprise
        # at QueueItem.compose (CORE-011): surface it now so supported() refuses
        # to arm an adapter whose format template cannot actually format.
        if skill_format:
            ok_fmt, fmt_reason = validate_skill_format(skill_format)
            if not ok_fmt:
                problems.append(fmt_reason)
        self.problems = list(problems)

        # Public so the arming path can ask "does this adapter CLAIM a
        # blocker" without touching the compiled pattern (the mixin's arm
        # guard reads it and refuses to arm when the claimed blocker cannot
        # run — a dead getattr here silently disabled that refusal, P0-9).
        self.blocker_pattern = blocker_pattern or ""
        self._blocker = None
        if self.blocker_pattern:
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

    def live_cdp_port(self):
        """The port right now: the file wins, because the file is current."""
        from fastprompter.core.watcher.cdp import port_from_file
        return port_from_file(self.cdp_port_file) or self.cdp_port

    def blocked(self, text):
        """Does the target's visible text say now is a bad moment?

        A permission prompt is silent, so the probes would call it idle -
        this is the override that stops a send landing on one.
        """
        if self._blocker is None or not text:
            return False
        return bool(self._blocker.search(text))

    def blocker_supported(self):
        """Whether a blocker_pattern can actually run for this transport.

        The blocker matches the TARGET'S VISIBLE text. Only a transport that
        can read it (CDP page text) may claim the safety; anything else would
        silently advertise protection that never executes (T-757).
        """
        return self.transport == "cdp"

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
    if entry.get("blocker_pattern") and entry.get("transport") != "cdp":
        # Never advertise a blocker this transport cannot execute (T-757).
        problems.append(
            "blocker_pattern is set, but this transport cannot read the "
            "target's visible text — the blocker is INACTIVE")

    # A TOML boolean is a real bool. Anything else (a quoted "false" string,
    # a 0/1) must NOT be silently coerced by bool(): bool("false") is True,
    # so a deliberately-disabled adapter would be enabled and armed. Reject
    # the entry so the typo surfaces instead of inverting the intent.
    enabled_raw = entry.get("enabled", True)
    if isinstance(enabled_raw, bool):
        enabled = enabled_raw
    else:
        raise ValueError(
            f"enabled must be a boolean (true/false), got {enabled_raw!r}")

    return Adapter(
        name=name.strip(),
        probes=probes,
        enabled=enabled,
        settle_ms=entry.get("settle_ms", 2500),
        submit=entry.get("submit", "enter"),
        multiline=entry.get("multiline", "join"),
        skill_format=entry.get("skill_format"),
        blocker_pattern=entry.get("blocker_pattern", ""),
        transport=entry.get("transport", ""),
        cdp_port=entry.get("cdp_port", 0),
        cdp_title=entry.get("cdp_title", ""),
        cdp_port_file=entry.get("cdp_port_file", ""),
        cdp_selector=entry.get("cdp_selector", ""),
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
        if key not in limits:
            errors.append(f"unknown limit {key!r}")
            continue
        # Clamp at the parse boundary: a config typo must not disarm the
        # engine's guards (T-757).
        if key == "min_gap_ms":
            try:
                limits[key] = max(0, int(value))
            except (TypeError, ValueError):
                errors.append(f"min_gap_ms must be a number, got {value!r}")
        elif key == "max_sends":
            try:
                limits[key] = max(1, int(value))
            except (TypeError, ValueError):
                errors.append(f"max_sends must be a number, got {value!r}")
        elif key == "dry_run_new":
            # Require a native TOML boolean. bool("false") is True, so a
            # quoted "false" would silently flip dry-run OFF (or "true"
            # would keep it on but mean nothing) — the launcher would then
            # actually send, which is the unsafe behaviour we must never
            # derive from a malformed config. A bad value keeps the safe
            # default (True) and is reported.
            if isinstance(value, bool):
                limits[key] = value
            else:
                errors.append(f"dry_run_new must be a boolean, got {value!r}")
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
