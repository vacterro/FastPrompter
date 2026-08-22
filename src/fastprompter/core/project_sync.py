"""Sync-Project — folder <-> silo two-way sync, pure logic (Qt-free).

The UI wiring lives in main.py (QFileSystemWatcher, debounce timers); this
module holds everything that must be deterministic and testable:

* which files are text files we should sync (include/exclude matching)
* scanning a folder into a sorted list of relative paths
* EOL detection so a file edited on Windows keeps its \\r\\n on write-back
* reading a file safely (size cap, binary sniff) and writing it atomically
* the slot <-> file mapping helpers

Semantics (documented once, here):

* A Sync-Project binds a project tab to a folder. Every text file that
  passes the include/exclude filters becomes a silo (slot 0..N-1 in file
  name order; extra files become new silos up to the 100-silo cap).
* Two-way and live: app edits are pushed to the file (debounced, and on
  every DB save), external file changes are applied back into the silo
  unless the silo holds unsaved app-side text (the app side wins while it
  is being typed).
* Exclude patterns match the file NAME (fnmatch-style) or any path
  component (substring). ``node_modules`` excludes a directory anywhere in
  the tree; ``*.min.js`` excludes those files anywhere.
"""

from __future__ import annotations

import fnmatch
import os

# Files with these extensions are treated as text by default ("all normal
# popular readable files with text").
DEFAULT_INCLUDE = (
    ".txt", ".md", ".markdown", ".rst", ".py", ".pyw", ".js", ".mjs", ".cjs",
    ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".conf", ".csv", ".tsv", ".html", ".htm", ".css", ".scss", ".less",
    ".xml", ".svg", ".log", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
    ".sql", ".r", ".rb", ".go", ".rs", ".java", ".kt", ".kts", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".hh", ".cs", ".php", ".swift", ".lua", ".pl",
    ".pm", ".vim", ".env", ".properties", ".gradle", ".dockerfile",
    ".dockerignore", ".gitignore", ".editorconfig", ".yml", ".makefile",
)

# Default excludes: junk/build/VCS directories and binary-ish files. A name
# with a ``*`` is fnmatch'd against the basename; anything else matches a
# path component (so "node_modules" excludes the directory at any depth).
DEFAULT_EXCLUDE = (
    "node_modules", ".git", ".hg", ".svn", ".idea", ".vscode", ".vs",
    "__pycache__", ".venv", "venv", "env", "dist", "build", "out", "target",
    "bin", "obj", ".next", ".nuxt", ".gradle", ".terraform", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".cache", "coverage", ".tox", ".eggs",
    "site-packages", "Pods", "vendor", ".DS_Store", "Thumbs.db",
    "desktop.ini", "*.pyc", "*.pyo", "*.exe", "*.dll", "*.so", "*.dylib",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.ico", "*.webp",
    "*.mp3", "*.mp4", "*.wav", "*.zip", "*.rar", "*.7z", "*.tar", "*.gz",
    "*.min.js", "*.min.css", "*.map", "*.woff", "*.woff2", "*.ttf", "*.otf",
    "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx",
)

DEFAULT_MAX_BYTES = 512 * 1024  # files larger than this are skipped


def parse_ext_list(raw: str) -> list[str]:
    """".txt .md, py" -> ['.txt', '.md', '.py'] (lowercased, dotted)."""
    out: list[str] = []
    for part in (raw or "").replace(",", " ").split():
        part = part.strip().lower()
        if not part:
            continue
        if not part.startswith("."):
            part = "." + part
        if part not in out:
            out.append(part)
    return out


def parse_exclude_list(raw: str) -> list[str]:
    """Comma/space separated exclude patterns, cleaned."""
    out: list[str] = []
    for part in (raw or "").replace(",", " ").split():
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def match_exclude(relpath: str, patterns: list[str]) -> bool:
    """Does ``relpath`` (POSIX-style, relative to the sync root) match?"""
    if not patterns:
        return False
    parts = relpath.split("/")
    for pattern in patterns:
        if not pattern:
            continue
        if "*" in pattern or "?" in pattern:
            if fnmatch.fnmatch(relpath, pattern) or fnmatch.fnmatch(parts[-1], pattern):
                return True
        elif pattern in parts:
            return True
    return False


def is_text_file(relpath: str, include: list[str] | None = None,
                 exclude: list[str] | None = None) -> bool:
    """Include/exclude decision for one relative path (pure)."""
    if match_exclude(relpath, exclude or []):
        return False
    ext = os.path.splitext(relpath)[1].lower()
    inc = include if include is not None else list(DEFAULT_INCLUDE)
    if not inc:
        return False
    return ext in inc


def scan_folder(root: str, include: list[str] | None = None,
                exclude: list[str] | None = None, recursive: bool = True,
                max_bytes: int = DEFAULT_MAX_BYTES) -> list[str]:
    """Every text file under ``root`` as a sorted list of relative paths.

    Pure and defensive: unreadable entries are skipped, never raised on.
    """
    root = os.path.abspath(root)
    inc = include if include is not None else list(DEFAULT_INCLUDE)
    exc = exclude if exclude is not None else list(DEFAULT_EXCLUDE)
    found: list[str] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            # prune excluded directories in place so os.walk never descends
            dirnames[:] = [d for d in dirnames if not match_exclude(
                os.path.relpath(os.path.join(dirpath, d), root).replace("\\", "/"),
                exc)]
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
                if not is_text_file(rel, inc, exc):
                    continue
                try:
                    if os.path.getsize(os.path.join(dirpath, name)) > max_bytes:
                        continue
                except OSError:
                    continue
                found.append(rel)
    else:
        try:
            names = os.listdir(root)
        except OSError:
            return []
        for name in names:
            rel = name.replace("\\", "/")
            path = os.path.join(root, name)
            if not (os.path.isfile(path) and is_text_file(rel, inc, exc)):
                continue
            try:
                if os.path.getsize(path) > max_bytes:
                    continue
            except OSError:
                continue
            found.append(rel)
    return sorted(found)


def detect_eol(text: str) -> str:
    """The dominant line ending: '\\r\\n' or '\\n' (defaults to '\\n')."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def looks_binary(data: bytes) -> bool:
    """NUL bytes in the first 8 KB -> binary, not text."""
    return b"\x00" in data[:8192]


def read_text_file(path: str, max_bytes: int = DEFAULT_MAX_BYTES):
    """Read ``path`` as text. Returns ``(text, eol)`` or None (skip it).

    None means: missing, too large, or binary — the caller must treat it as
    "not a syncable text file right now". The returned text is EOL-
    NORMALISED (\n only); ``eol`` is the file's dominant line ending, to be
    re-applied on write-back.
    """
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            return None
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if looks_binary(data):
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Not UTF-8 (e.g. legacy cp1251/win-1251 notes): still a text
            # file the user may legitimately edit. Decode lossily rather
            # than refusing the file.
            text = data.decode("utf-8", errors="replace")
    eol = detect_eol(text)
    return text.replace("\r\n", "\n"), eol


def write_text_file(path: str, text: str, eol: str = "\n") -> str | None:
    """Write ``text`` with the file's EOL, atomically (temp + rename).

    Returns the text ACTUALLY written (EOL-normalised) so callers can store
    it as the "last applied" baseline — comparing a \\n-only silo text
    against a \\r\\n file would otherwise look like an external edit.
    Returns None on failure."""
    if eol != "\n":
        text = text.replace("\n", eol)
    tmp = path + ".fp-sync-tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return text
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None


def free_slots(mapping: dict, total: int, count: int) -> list[int]:
    """The first ``count`` slots not claimed by ``mapping``.

    ``mapping`` maps str(slot) -> relpath. Slots are allocated from the end
    of the silo list (appending) or the first free gap, newest files first —
    but to keep the mapping stable across rescans, new files simply take the
    lowest unclaimed slot at or after ``total``.
    """
    claimed = {int(k) for k in mapping}
    slots: list[int] = []
    slot = total
    while len(slots) < count:
        if slot >= 100:  # hard cap, matches MAX_SILOS_PER_CATEGORY
            break
        if slot not in claimed:
            slots.append(slot)
        slot += 1
    return slots
