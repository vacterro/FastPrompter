"""Smart Code Runner — detection engine (T-1456).

Qt-free, stdlib-only. Detects executable code in editor text and returns
structured candidates with language, ranges, confidence, and ambiguity.

Precedence:
  1. Explicit user selection
  2. Fenced code block at caret
  3. Single unambiguous executable code block
  4. High-confidence standalone document
  5. Otherwise require manual language selection

Never concatenates unrelated blocks. Never infers executable code from
prose mentioning commands or languages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CodeCandidate:
    """One detected runnable code region."""

    language: str
    source: str
    start: int          # char offset in document
    end: int
    confidence: float   # 0.0–1.0
    reason: str
    ambiguous: bool = False
    document_id: str = ""
    revision: int = 0


# ---------------------------------------------------------------------------
# Language patterns
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r'^```(\w+)\s*\n(.*?)^```', re.MULTILINE | re.DOTALL)
_SHEBANG_RE = re.compile(r'^#!\s*(?:/usr/bin/env\s+)?(\S+)', re.MULTILINE)

_PS_VERBS = (
    r'Set-Location', r'Get-', r'New-Item', r'Join-Path', r'Split-Path',
    r'Test-Path', r'Copy-Item', r'Move-Item', r'Remove-Item', r'Rename-Item',
    r'Get-Content', r'Set-Content', r'Add-Content', r'Clear-Content',
    r'Select-String', r'Where-Object', r'ForEach-Object', r'Sort-Object',
    r'Measure-Object', r'Group-Object', r'Start-Process', r'Stop-Process',
    r'Wait-Process', r'Invoke-Expression', r'Invoke-Command',
    r'ConvertTo-Json', r'ConvertFrom-Json', r'Write-Host', r'Write-Output',
    r'Out-Null', r'Out-File', r'Out-String',
    r'try\s*\{', r'catch\s*\{', r'finally\s*\{', r'throw\s+',
    r'param\s*\(', r'function\s+\w+', r'filter\s+\w+',
    r'\$[A-Za-z_][A-Za-z0-9_]*\s*=', r'\$env:',
)
_PS_RE = re.compile('|'.join(_PS_VERBS), re.IGNORECASE)

_CMD_RE = re.compile(
    r'\b(echo|set|if\s+exist|if\s+not\s+exist|for\s+/[a-z]|goto|call|rem|'
    r'@echo\s+off|pause|exit\s+/[a-z]|del\s+/[a-z]|copy\s+/[a-z]|'
    r'move\s+/[a-z]|ren\s+/[a-z]|type\s+|dir\s+/[a-z]|cd\s+/[a-z])\b',
    re.IGNORECASE)

_PY_RE = re.compile(
    r'\b(def\s+\w+\s*\(|import\s+\w+|from\s+\w+\s+import|class\s+\w+|'
    r'if\s+__name__|print\s*\(|with\s+open\s*\(|raise\s+\w+|'
    r'async\s+def|yield\s+from|lambda\s+|@\w+\.)')

_JS_RE = re.compile(
    r'\b(function\s+\w+|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|'
    r'=>|console\.log\s*\(|require\s*\(|import\s+.*\s+from\s+|'
    r'export\s+(default|const|function|class)|module\.exports)')

_AHK_RE = re.compile(
    r'\b(MsgBox|Run\s+|RunWait|Sleep\s+|Send\s+|SendInput|'
    r'FileAppend|FileRead|FileDelete|WinActivate|WinWait|'
    r'#Persistent|#SingleInstance|#Include|Hotkey\s+)', re.IGNORECASE)

_RUBY_RE = re.compile(
    r'\b(def\s+\w+|require\s+|puts\s+|attr_accessor|attr_reader|'
    r'class\s+\w+\s*<|module\s+\w+|end\s*$|do\s*\|)', re.MULTILINE)

_PHP_RE = re.compile(r'<\?php|\bfunction\s+\w+\s*\(|\$\w+\s*=|echo\s+|require_once\s*\(')

_PERL_RE = re.compile(r'\b(use\s+\w+|my\s+\$\w+|print\s+|sub\s+\w+|foreach\s+my\b)')

_LUA_RE = re.compile(r'\b(local\s+\w+|function\s+\w+|require\s*\(|print\s*\(|io\.(open|write|read))')

# Map language key -> (display name, interpreter key)
LANGUAGE_INFO: dict[str, tuple[str, str]] = {
    "powershell": ("PowerShell", "powershell"),
    "pwsh": ("PowerShell 7+", "pwsh"),
    "cmd": ("CMD/Batch", "cmd"),
    "python": ("Python", "python"),
    "javascript": ("JavaScript (Node)", "node"),
    "js": ("JavaScript (Node)", "node"),
    "ahk": ("AutoHotkey", "ahk"),
    "ahk2": ("AutoHotkey v2", "ahk2"),
    "vbs": ("VBScript", "cscript"),
    "bash": ("Bash", "bash"),
    "ruby": ("Ruby", "ruby"),
    "php": ("PHP", "php"),
    "perl": ("Perl", "perl"),
    "lua": ("Lua", "lua"),
}

# Fenced language aliases -> canonical key
_FENCE_ALIASES = {
    "ps": "powershell", "ps1": "powershell", "powershell": "powershell",
    "pwsh": "pwsh",
    "bat": "cmd", "cmd": "cmd", "batch": "cmd", "shell": "cmd",
    "py": "python", "python": "python", "python3": "python",
    "js": "javascript", "javascript": "javascript", "node": "javascript", "nodejs": "javascript",
    "ahk": "ahk", "ahk2": "ahk2", "autohotkey": "ahk",
    "vbs": "vbs", "vbscript": "vbs",
    "sh": "bash", "bash": "bash", "zsh": "bash",
    "rb": "ruby", "ruby": "ruby",
    "php": "php",
    "pl": "perl", "perl": "perl",
    "lua": "lua",
}

# Shebang interpreter -> canonical key
_SHEBANG_MAP = {
    "python": "python", "python3": "python", "python2": "python",
    "node": "javascript", "nodejs": "javascript",
    "bash": "bash", "sh": "bash", "zsh": "bash",
    "ruby": "ruby", "perl": "perl", "php": "php", "lua": "lua",
    "pwsh": "pwsh", "powershell": "powershell",
}


def _score(text: str) -> dict[str, float]:
    """Score text against all language patterns. Returns {lang: ratio}."""
    lines = max(len(text.splitlines()), 1)
    return {
        "powershell": len(_PS_RE.findall(text)) / lines,
        "cmd": len(_CMD_RE.findall(text)) / lines,
        "python": len(_PY_RE.findall(text)) / lines,
        "javascript": len(_JS_RE.findall(text)) / lines,
        "ahk": len(_AHK_RE.findall(text)) / lines,
        "ruby": len(_RUBY_RE.findall(text)) / lines,
        "php": len(_PHP_RE.findall(text)) / lines,
        "perl": len(_PERL_RE.findall(text)) / lines,
        "lua": len(_LUA_RE.findall(text)) / lines,
    }


def _best(scores: dict[str, float], threshold: float = 0.05) -> tuple[str, float]:
    """Return (lang, score) for the best-scoring language, or ("", 0)."""
    if not scores:
        return ("", 0.0)
    lang = max(scores, key=scores.get)
    score = scores[lang]
    if score < threshold:
        return ("", 0.0)
    return (lang, min(score, 0.8))


def _is_prose(text: str) -> bool:
    """Heuristic: is this ordinary prose, not code?"""
    stripped = text.strip()
    if not stripped:
        return True
    # High ratio of natural-language words, low code density
    words = re.findall(r'[a-zA-Z]+', stripped)
    if not words:
        return False
    code_chars = len(re.findall(r'[{}();=<>|&\[\]]', stripped))
    return code_chars / max(len(stripped), 1) < 0.02 and len(words) > 20


def detect_from_fence(text: str) -> list[CodeCandidate]:
    """Extract all fenced code blocks with language annotation."""
    candidates = []
    for m in _FENCE_RE.finditer(text):
        lang_raw = m.group(1).lower()
        lang = _FENCE_ALIASES.get(lang_raw, lang_raw)
        if lang not in LANGUAGE_INFO:
            continue
        source = m.group(2)
        if not source.strip():
            continue  # empty fence is not executable code
        candidates.append(CodeCandidate(
            language=lang,
            source=source,
            start=m.start(2),
            end=m.end(2),
            confidence=0.95,
            reason=f"fenced block ({lang_raw})",
        ))
    return candidates


def detect_from_shebang(text: str) -> CodeCandidate | None:
    """Detect shebang-identified scripts."""
    m = _SHEBANG_RE.match(text.strip())
    if not m:
        return None
    interp = m.group(1).split('/')[-1].lower()
    # Strip "env" prefix: "#!/usr/bin/env python" -> "python"
    if interp == "env":
        rest = text.strip()[m.end():].strip().split()
        if rest:
            interp = rest[0].lower()
    lang = _SHEBANG_MAP.get(interp)
    if not lang:
        return None
    return CodeCandidate(
        language=lang,
        source=text.strip(),
        start=0,
        end=len(text),
        confidence=0.9,
        reason=f"shebang ({interp})",
    )


def detect_document(text: str) -> CodeCandidate | None:
    """Detect a high-confidence standalone document (no fences)."""
    stripped = text.strip()
    if not stripped or _is_prose(stripped):
        return None
    scores = _score(stripped)
    lang, conf = _best(scores)
    if not lang:
        return None
    return CodeCandidate(
        language=lang,
        source=stripped,
        start=0,
        end=len(text),
        confidence=conf,
        reason="standalone document",
    )


def detect_at_caret(text: str, caret_pos: int) -> CodeCandidate | None:
    """Detect code at the caret position (inside a fenced block)."""
    for m in _FENCE_RE.finditer(text):
        block_start = m.start(2)
        block_end = m.end(2)
        if block_start <= caret_pos <= block_end:
            lang_raw = m.group(1).lower()
            lang = _FENCE_ALIASES.get(lang_raw, lang_raw)
            if lang not in LANGUAGE_INFO:
                return None
            return CodeCandidate(
                language=lang,
                source=m.group(2),
                start=block_start,
                end=block_end,
                confidence=0.95,
                reason=f"fenced block at caret ({lang_raw})",
            )
    return None


def detect_selection(text: str, sel_start: int, sel_end: int) -> CodeCandidate | None:
    """Detect code in an explicit user selection."""
    if sel_start >= sel_end:
        return None
    selected = text[sel_start:sel_end].strip()
    if not selected:
        return None
    # Fenced in selection
    if selected.startswith("```"):
        return detect_from_fence(selected)[0] if detect_from_fence(selected) else None
    # Shebang
    sb = detect_from_shebang(selected)
    if sb:
        return CodeCandidate(
            language=sb.language, source=selected,
            start=sel_start, end=sel_end,
            confidence=sb.confidence, reason="shebang (selection)",
        )
    # Heuristic
    if _is_prose(selected):
        return None
    scores = _score(selected)
    lang, conf = _best(scores)
    if not lang:
        return None
    return CodeCandidate(
        language=lang, source=selected,
        start=sel_start, end=sel_end,
        confidence=conf, reason="selection heuristic",
    )


def detect_all(
    text: str,
    *,
    caret_pos: int | None = None,
    sel_start: int | None = None,
    sel_end: int | None = None,
    document_id: str = "",
    revision: int = 0,
) -> list[CodeCandidate]:
    """Full detection pipeline. Returns candidates in precedence order.

    1. Explicit selection (if provided and non-empty)
    2. Fenced block at caret
    3. All fenced blocks (if unambiguous single block)
    4. Standalone document heuristic
    """
    # 1. Selection
    if sel_start is not None and sel_end is not None and sel_start < sel_end:
        sel = detect_selection(text, sel_start, sel_end)
        if sel:
            return [replace(sel, document_id=document_id, revision=revision)]

    # 2. Caret in fence
    if caret_pos is not None:
        at_caret = detect_at_caret(text, caret_pos)
        if at_caret:
            return [replace(at_caret, document_id=document_id,
                            revision=revision)]

    # 3. Fenced blocks
    fenced = detect_from_fence(text)
    if len(fenced) == 1:
        return [replace(fenced[0], document_id=document_id,
                        revision=revision)]
    if len(fenced) > 1:
        # Multiple blocks: return all, marked ambiguous
        return [replace(c, document_id=document_id, revision=revision,
                        ambiguous=True) for c in fenced]

    # 4. Standalone document
    doc = detect_document(text)
    if doc:
        return [replace(doc, document_id=document_id, revision=revision)]

    return []


def language_display(lang_key: str) -> str:
    """Human-readable language name."""
    return LANGUAGE_INFO.get(lang_key, (lang_key, ""))[0]


def interpreter_key(lang_key: str) -> str:
    """Interpreter registry key for a language."""
    return LANGUAGE_INFO.get(lang_key, ("", ""))[1]
