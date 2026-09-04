"""Multi-level troubleshooting and auto-healing for AI limit metrics.

Every vendor has distinct failure modes that trip up new users:

* **Codex**: CLI is installed but user hasn't run ``codex login`` (missing
  ``~/.codex/auth.json``), or CLI is not installed yet.
* **Claude**: CLI installed but unauthenticated, status-line bridge points to a
  stale interpreter path, or bridge is disconnected.
* **Antigravity**: data directory is relocated, or ``agy`` CLI is not installed
  (falling back to 429 refusals only).
* **ZCode**: disabled by default in settings even when a valid Coding Plan with
  an API key already exists on disk, or config is in a candidate path.

This module provides:
1. **Level 1 (Detection)**: Deep inspection of binaries, configs, auth tokens,
   and bridges with human-actionable issue descriptions.
2. **Level 2 (Auto-Healing)**: Automated, safe repairs (stale bridge repair,
   candidate path adoption, auto-enabling detected valid plans, auto-enabling
   header gauges).
3. **Level 3 (One-Click Launchers)**: Interactive console launchers for CLI
   logins (``codex login``, ``claude login``, ``agy auth login``) and official
   installers.
"""

from __future__ import annotations

from typing import Any

from fastprompter.core.usage_limits import cli_tools
from fastprompter.core.usage_limits.providers import (
    antigravity as agy_prov,
)
from fastprompter.core.usage_limits.providers import (
    claude as claude_prov,
)
from fastprompter.core.usage_limits.providers import (
    codex as codex_prov,
)
from fastprompter.core.usage_limits.providers import (
    zcode as zcode_prov,
)

VENDOR_KEYS = ("codex", "claude", "antigravity", "zcode")

VENDOR_TITLES = {
    "codex": "Codex (OpenAI)",
    "claude": "Claude Code (Anthropic)",
    "antigravity": "Antigravity (Google)",
    "zcode": "ZCode (GLM Coding Plan)",
}


def diagnose_vendor(vendor: str, data: dict | None = None) -> dict[str, Any]:
    """Inspect one vendor and return structured diagnosis with repair paths."""
    data = data or {}
    title = VENDOR_TITLES.get(vendor, vendor.title())

    if vendor == "codex":
        return _diagnose_codex(title, data)
    elif vendor == "claude":
        return _diagnose_claude(title, data)
    elif vendor == "antigravity":
        return _diagnose_antigravity(title, data)
    elif vendor == "zcode":
        return _diagnose_zcode(title, data)
    else:
        return {
            "vendor": vendor,
            "title": title,
            "installed": False,
            "authenticated": False,
            "ready": False,
            "status_code": "unknown",
            "summary": f"Unknown vendor {vendor!r}",
            "issues": [f"Provider {vendor!r} is not recognized"],
            "recommendations": [],
            "auto_heals_available": [],
            "manual_actions": [],
            "details": {},
        }


def _diagnose_codex(title: str, data: dict) -> dict[str, Any]:
    extra = data.get("limit_codex_homes")
    homes_list = [h.strip() for h in str(extra or "").split(",") if h.strip()]
    try:
        status = codex_prov.source_status(homes_list)
    except Exception as exc:
        status = {"cli_installed": False, "cli_path": "", "homes": [],
                  "auth_found": False, "error": str(exc)}

    cli_ok = status.get("cli_installed", False)
    auth_ok = status.get("auth_found", False)
    homes = status.get("homes", [])

    issues = []
    recommendations = []
    auto_heals = []
    manual_actions = []

    if not cli_ok:
        status_code = "needs_install"
        summary = "CLI not installed"
        issues.append("Codex CLI is not installed on PATH or standard directories.")
        recommendations.append("Install Codex CLI via official installer.")
        manual_actions.append({"action": "install", "label": "Install Codex CLI", "key": "codex"})
    elif not auth_ok:
        status_code = "needs_login"
        summary = "CLI installed · not logged in"
        issues.append("Codex CLI is installed, but no active login session (auth.json) was found.")
        recommendations.append("Run 'codex login' in a console to authenticate.")
        manual_actions.append({"action": "login", "label": "Log in to Codex…", "key": "codex"})
    else:
        status_code = "ready"
        summary = f"Ready · {len(homes)} home(s) reporting"

    return {
        "vendor": "codex",
        "title": title,
        "installed": cli_ok,
        "authenticated": auth_ok,
        "ready": cli_ok and auth_ok,
        "status_code": status_code,
        "summary": summary,
        "issues": issues,
        "recommendations": recommendations,
        "auto_heals_available": auto_heals,
        "manual_actions": manual_actions,
        "details": status,
    }


def _diagnose_claude(title: str, data: dict) -> dict[str, Any]:
    try:
        status = claude_prov.source_status()
    except Exception as exc:
        status = {"cli_installed": False, "bridge_connected": False, "error": str(exc)}

    try:
        from fastprompter.core.usage_limits.claude_statusline import bridge_status
        b_stat = bridge_status()
    except Exception:
        b_stat = {}

    cli_ok = status.get("cli_installed", False)
    b_connected = b_stat.get("connected", False)
    b_stale = b_stat.get("stale", False)
    b_cache = b_stat.get("has_cache", False)
    desktop_fresh = status.get("desktop_fresh", False)

    issues = []
    recommendations = []
    auto_heals = []
    manual_actions = []

    if b_stale:
        status_code = "stale_bridge"
        summary = "Old status-line connection detected"
        issues.append("Claude Code status-line bridge points to a previous FastPrompter installation.")
        recommendations.append("Repair the status-line bridge to reconnect quota updates.")
        auto_heals.append("repair_bridge")
        manual_actions.append({"action": "repair_bridge", "label": "Reconnect Claude Code", "key": "claude"})
    elif b_connected and b_cache:
        status_code = "ready"
        summary = "Ready · status-line active"
    elif cli_ok and (status.get("desktop_windows") or b_connected):
        status_code = "ready"
        summary = "Ready · CLI & sampler active"
    elif cli_ok:
        status_code = "needs_connect"
        summary = "CLI installed · bridge disconnected"
        recommendations.append("Connect the Claude Code status-line bridge for live session quotas.")
        auto_heals.append("connect_bridge")
        manual_actions.append({"action": "connect_bridge", "label": "Connect Claude Code", "key": "claude"})
    else:
        status_code = "needs_install"
        summary = "CLI not installed"
        issues.append("Claude Code CLI is not installed on PATH or standard directories.")
        recommendations.append("Install Claude Code CLI via official installer.")
        manual_actions.append({"action": "install", "label": "Install Claude Code CLI", "key": "claude"})

    ready = (b_connected and b_cache) or cli_ok or desktop_fresh

    return {
        "vendor": "claude",
        "title": title,
        "installed": cli_ok or b_connected or bool(status.get("desktop_windows")),
        "authenticated": ready,
        "ready": ready,
        "status_code": status_code,
        "summary": summary,
        "issues": issues,
        "recommendations": recommendations,
        "auto_heals_available": auto_heals,
        "manual_actions": manual_actions,
        "details": status,
    }


def _diagnose_antigravity(title: str, data: dict) -> dict[str, Any]:
    dir_cfg = str(data.get("limit_antigravity_dir", "") or "").strip()
    try:
        status = agy_prov.source_status(dir_cfg or None)
    except Exception as exc:
        status = {"installed": False, "cli_installed": False, "error": str(exc)}

    app_installed = status.get("installed", False)
    cli_installed = status.get("cli_installed", False)
    candidates = status.get("candidate_dirs", [])

    issues = []
    recommendations = []
    auto_heals = []
    manual_actions = []

    if not app_installed and candidates and not dir_cfg:
        status_code = "relocated"
        summary = f"Candidate data found at {candidates[0]}"
        recommendations.append(f"Adopt candidate data path {candidates[0]}.")
        auto_heals.append("adopt_data_dir")
    elif not app_installed:
        status_code = "not_found"
        summary = "Antigravity data not found"
        issues.append("Antigravity directory (~/.gemini/antigravity) was not found.")
        recommendations.append("Specify custom Antigravity folder in Sources settings if relocated.")
    elif not cli_installed:
        status_code = "refusals_only"
        summary = "App installed · CLI missing (refusals only)"
        issues.append("Antigravity CLI (agy) is not installed. Without it, only 429 rate limit refusals are readable, not exact percentages.")
        recommendations.append("Install Antigravity CLI (agy) for exact quota percentages.")
        manual_actions.append({"action": "install", "label": "Install Antigravity CLI (agy)", "key": "antigravity"})
    else:
        status_code = "ready"
        summary = "Ready · CLI installed"

    ready = app_installed

    return {
        "vendor": "antigravity",
        "title": title,
        "installed": app_installed or cli_installed,
        "authenticated": app_installed,
        "ready": ready,
        "status_code": status_code,
        "summary": summary,
        "issues": issues,
        "recommendations": recommendations,
        "auto_heals_available": auto_heals,
        "manual_actions": manual_actions,
        "details": status,
    }


def _diagnose_zcode(title: str, data: dict) -> dict[str, Any]:
    cfg_path = str(data.get("limit_zcode_config", "") or "").strip()
    enabled = str(data.get("limit_zcode_enabled", "False")) == "True"
    try:
        status = zcode_prov.source_status(cfg_path or None, enabled=enabled)
    except Exception as exc:
        status = {"config_found": False, "plans": [], "error": str(exc)}

    config_found = status.get("config_found", False)
    candidates = status.get("candidate_configs", [])
    plans = status.get("plans", [])
    usable_plans = [p for p in plans if p.get("has_key") and p.get("endpoint")]

    issues = []
    recommendations = []
    auto_heals = []
    manual_actions = []

    if not config_found and candidates and not cfg_path:
        status_code = "relocated"
        summary = f"Candidate config found at {candidates[0]}"
        recommendations.append(f"Adopt candidate config path {candidates[0]}.")
        auto_heals.append("adopt_config_path")
    elif not config_found:
        status_code = "no_config"
        summary = "ZCode config not found"
        issues.append("ZCode config file (~/.zcode/v2/config.json) was not found.")
    elif usable_plans and not enabled:
        status_code = "disabled_with_plans"
        summary = f"{len(usable_plans)} Coding Plan(s) detected · disabled"
        issues.append(f"Found {len(usable_plans)} active ZCode Coding Plan(s) on your system, but reading ZCode limits is disabled.")
        recommendations.append("Enable ZCode limits to begin monitoring quota.")
        auto_heals.append("enable_zcode")
        manual_actions.append({"action": "enable_zcode", "label": "Enable detected ZCode Plan", "key": "zcode"})
    elif not usable_plans:
        status_code = "no_plan_keys"
        summary = "Config found · no active Coding Plan key"
        issues.append("ZCode config is present, but has no API key for a Coding Plan.")
        recommendations.append("Log in to your GLM Coding Plan in the ZCode app.")
    else:
        status_code = "ready"
        summary = f"Ready · {len(usable_plans)} plan(s) active"

    ready = config_found and bool(usable_plans) and enabled

    return {
        "vendor": "zcode",
        "title": title,
        "installed": config_found or bool(candidates),
        "authenticated": bool(usable_plans),
        "ready": ready,
        "status_code": status_code,
        "summary": summary,
        "issues": issues,
        "recommendations": recommendations,
        "auto_heals_available": auto_heals,
        "manual_actions": manual_actions,
        "details": status,
    }


def diagnose_all(data: dict | None = None) -> dict[str, dict[str, Any]]:
    """Run diagnostics across all vendors."""
    data = data or {}
    return {v: diagnose_vendor(v, data) for v in VENDOR_KEYS}


def auto_heal_all(data: dict, service: Any = None) -> dict[str, Any]:
    """Execute all automated safe repairs across all vendors.

    Safe repairs include:
    * Re-installing stale Claude status-line bridge.
    * Connecting Claude status-line bridge if CLI is installed.
    * Adopting candidate config paths for ZCode / Antigravity if standard paths missing.
    * Enabling ZCode if an active Coding Plan with API key is already present.
    * Turning on limit_gauges so gauges immediately appear in the header.
    * Triggering service discovery and refresh.
    """
    healed: list[str] = []
    diag = diagnose_all(data)

    # 1. Claude auto-heal
    claude_diag = diag.get("claude", {})
    if "repair_bridge" in claude_diag.get("auto_heals_available", []):
        try:
            from fastprompter.core.usage_limits.claude_statusline import install_bridge
            install_bridge()
            healed.append("Repaired stale Claude Code status-line bridge")
        except Exception:
            pass
    elif "connect_bridge" in claude_diag.get("auto_heals_available", []):
        try:
            from fastprompter.core.usage_limits.claude_statusline import install_bridge
            install_bridge()
            healed.append("Connected Claude Code status-line bridge")
        except Exception:
            pass

    # 2. Antigravity candidate path adoption
    agy_diag = diag.get("antigravity", {})
    if "adopt_data_dir" in agy_diag.get("auto_heals_available", []):
        cands = agy_diag.get("details", {}).get("candidate_dirs", [])
        if cands:
            data["limit_antigravity_dir"] = cands[0]
            healed.append(f"Configured Antigravity data folder: {cands[0]}")

    # 3. ZCode candidate path adoption & plan enabling
    z_diag = diag.get("zcode", {})
    if "adopt_config_path" in z_diag.get("auto_heals_available", []):
        cands = z_diag.get("details", {}).get("candidate_configs", [])
        if cands:
            data["limit_zcode_config"] = cands[0]
            healed.append(f"Configured ZCode config path: {cands[0]}")
            # Re-diagnose zcode with adopted path to see if plans are now detected
            z_diag = diagnose_vendor("zcode", data)

    if "enable_zcode" in z_diag.get("auto_heals_available", []):
        data["limit_zcode_enabled"] = "True"
        plans = [p["label"] for p in z_diag.get("details", {}).get("plans", []) if p.get("has_key")]
        plan_desc = ", ".join(plans) if plans else "Coding Plan"
        healed.append(f"Enabled detected ZCode limits ({plan_desc})")

    # 4. Auto-enable header gauges if limits are now available
    if str(data.get("limit_gauges", "False")) != "True":
        data["limit_gauges"] = "True"
        healed.append("Enabled AI limit gauges in the main window header")

    # 5. Service discovery & refresh
    accounts_count = 0
    if service is not None:
        try:
            service.reconfigure(data)
            service.discover()
            service.refresh()
            accounts_count = len(getattr(service.state_copy, "accounts", []) or [])
        except Exception:
            pass

    # Post-repair diagnostic state
    post_diag = diagnose_all(data)

    remaining_issues: list[str] = []
    for vendor, report in post_diag.items():
        if not report.get("ready"):
            for issue in report.get("issues", []):
                remaining_issues.append(f"{report['title']}: {issue}")

    return {
        "healed": healed,
        "remaining_issues": remaining_issues,
        "diagnostics": post_diag,
        "accounts_count": accounts_count,
    }


def launch_vendor_login(vendor: str) -> None:
    """Launch interactive console login for the given vendor."""
    cli_tools.launch_login(vendor)


def launch_vendor_install(vendor: str) -> None:
    """Launch official installer for the given vendor."""
    cli_tools.launch_installer(vendor)
