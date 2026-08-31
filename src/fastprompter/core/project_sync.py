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
import re

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


def resolve_relative_path(root: str, relpath: str) -> str | None:
    """Resolve a persisted project-relative path without leaving *root*.

    Sync mappings live in the profile database, so they must be treated as
    untrusted input (old versions, hand-edited profiles, or a moved folder
    can all leave a stale mapping behind). ``realpath`` also closes the
    symlink escape case: a path that looks relative can still point outside
    the sync root after resolution.
    """
    if not isinstance(root, str) or not isinstance(relpath, str):
        return None
    # Normalize only the path SEPARATOR. Do NOT strip() the filename: leading
    # and trailing whitespace are legal characters in a filesystem name, so
    # stripping would alias distinct Sync-Project entries (" lead.txt" vs
    # "lead.txt") onto one target. Only the Windows backslash -> POSIX slash
    # conversion is applied here; the filename is preserved byte-for-character.
    relpath = relpath.replace("\\", "/")
    if not relpath or relpath.startswith("/") or re.match(r"^[A-Za-z]:/", relpath):
        return None
    root_real = os.path.realpath(os.path.abspath(root))
    candidate = os.path.realpath(os.path.join(root_real, *relpath.split("/")))
    try:
        if os.path.commonpath((root_real, candidate)) != root_real:
            return None
    except ValueError:  # different drives on Windows
        return None
    return candidate


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
    """Include/exclude decision for one relative path (pure).

    Include tokens match EITHER an extension (``.py`` -> ``x.py``) OR an exact
    special basename (``.env``, ``.gitignore``, ``.dockerignore``,
    ``.editorconfig``, ``.makefile``, ``.dockerfile`` — extensionless or
    dot-prefixed config files the include inventory advertises but an
    extension-only matcher could never reach, W2-007). A plain extensionless
    name like ``Dockerfile``/``Makefile`` matches when the token equals the
    basename (case-insensitive, ``.dockerfile``/``.makefile``)."""
    if match_exclude(relpath, exclude or []):
        return False
    ext = os.path.splitext(relpath)[1].lower()
    inc = include if include is not None else list(DEFAULT_INCLUDE)
    if not inc:
        return False
    if ext in inc:
        return True
    # W2-007: special basename match. Compare the final component
    # case-insensitively against the include tokens so advertised dotfiles and
    # extensionless build files are discoverable, not silently excluded.
    base = os.path.basename(relpath)
    base_l = base.lower()
    for tok in inc:
        tok_l = tok.strip().lower()
        if not tok_l:
            continue
        if tok_l.startswith("."):
            if base_l == tok_l or base_l == tok_l.lstrip("."):
                return True
        elif base_l == tok_l:
            return True
    return False


def is_sync_eligible(relpath: str, include: list[str] | None = None,
                     exclude: list[str] | None = None,
                     recursive: bool = True) -> bool:
    """The CONFIGURATION-only eligibility predicate (W2-001).

    This decides what MAY sync: extension/basename include/exclude, and the
    recursive flat/nested rule. It deliberately does NOT fold size,
    readability, or current existence into the verdict — a path that is
    configured-eligible stays eligible while momentarily unreadable,
    oversized, or absent, so transient OS state never changes the binding.
    """
    if not isinstance(relpath, str) or not relpath:
        return False
    if not recursive and "/" in relpath.replace("\\", "/"):
        return False
    return is_text_file(relpath, include, exclude)


def scan_folder(root: str, include: list[str] | None = None,
                exclude: list[str] | None = None, recursive: bool = True,
                max_bytes: int = DEFAULT_MAX_BYTES,
                limit: int | None = None,
                exclude_paths: set[str] | None = None,
                should_cancel: callable | None = None) -> list[str]:
    """Text files under ``root`` as a sorted list of relative paths.

    Pure and defensive: unreadable entries are skipped, never raised on.

    ``limit`` (PERF-001): bound the retained result to the lexicographically
    smallest K eligible paths using a max-heap, so discovery costs O(N log K)
    and O(K) memory instead of collecting and sorting ALL N (a large repo with
    only K<=100 binding slots would otherwise allocate/sort the entire tree on
    the GUI thread). ``limit=None`` keeps the exact legacy all-result contract.

    ``exclude_paths`` (W2-001): relative paths already mapped elsewhere are
    skipped BEFORE size/readability work, in both recursive and flat modes;
    separators are normalised to POSIX. ``should_cancel`` (W2-001): a
    callable consulted before traversal and during iteration; when it returns
    True the scan stops and returns [] — an empty result is the "cancelled"
    signal, never a partial list.
    """
    import heapq

    if should_cancel is not None and bool(should_cancel()):
        return []
    if exclude_paths:
        exclude_paths = {
            (p or "").replace("\\", "/") for p in exclude_paths
            if isinstance(p, str) and p
        }
    else:
        exclude_paths = set()

    class _NegStr:
        """String wrapper that REVERSES __lt__ so heapq's min-heap behaves as
        a max-heap on the underlying string: heap[0] is the lexicographically
        LARGEST retained path, which is the one to evict once the bound is hit
        (PERF-001)."""
        __slots__ = ("s",)

        def __init__(self, s):
            self.s = s

        def __lt__(self, other):
            return self.s > other.s

    root = os.path.abspath(root)
    inc = include if include is not None else list(DEFAULT_INCLUDE)
    exc = exclude if exclude is not None else list(DEFAULT_EXCLUDE)
    found: list[str] = []
    heap: list[_NegStr] = []      # PERF-001: bounded max-heap
    keep = 0 if limit is None else max(0, int(limit))

    def _add(rel):
        if keep == 0:
            found.append(rel)
            return
        if len(heap) < keep:
            heapq.heappush(heap, _NegStr(rel))
        elif rel < heap[0].s:
            heapq.heapreplace(heap, _NegStr(rel))

    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            if should_cancel is not None and bool(should_cancel()):
                return []
            # prune excluded directories in place so os.walk never descends
            dirnames[:] = [d for d in dirnames if not match_exclude(
                os.path.relpath(os.path.join(dirpath, d), root).replace("\\", "/"),
                exc)]
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
                if rel in exclude_paths:
                    continue
                if not is_text_file(rel, inc, exc):
                    continue
                try:
                    if os.path.getsize(os.path.join(dirpath, name)) > max_bytes:
                        continue
                except OSError:
                    continue
                _add(rel)
    else:
        try:
            names = os.listdir(root)
        except OSError:
            return []
        for name in names:
            rel = name.replace("\\", "/")
            path = os.path.join(root, name)
            if rel in exclude_paths:
                continue
            if not (os.path.isfile(path) and is_text_file(rel, inc, exc)):
                continue
            try:
                if os.path.getsize(path) > max_bytes:
                    continue
            except OSError:
                continue
            _add(rel)

    if keep == 0:
        return sorted(found)
    return sorted(w.s for w in heap)


def detect_eol(text: str) -> str:
    """The dominant line ending: '\\r\\n' or '\\n' (defaults to '\\n')."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def looks_binary(data: bytes) -> bool:
    """NUL bytes in the first 8 KB -> binary, not text."""
    return b"\x00" in data[:8192]


def read_text_file(path: str, max_bytes: int = DEFAULT_MAX_BYTES):
    """Read ``path`` as text. Returns ``(text, eol, had_utf8_bom)`` or None.

    None means: missing, too large, or binary — the caller must treat it as
    "not a syncable text file right now". The returned text is EOL-
    NORMALISED (\n only); ``eol`` is the file's dominant line ending and
    ``had_utf8_bom`` records whether the source carried a UTF-8 byte-order
    mark, both to be re-applied on write-back (CORE-007: BOM must survive a
    FastPrompter-originated edit instead of being silently dropped).
    """
    try:
        # W2-006: the opened stream is the authoritative bound. `getsize` is
        # only a cheap pre-check; the file may grow or be replaced between the
        # stat and the read, so the read itself must enforce the limit. Read at
        # most max_bytes + 1 and treat a present extra byte as "too large".
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None
    except OSError:
        return None
    if looks_binary(data):
        return None
    had_utf8_bom = data[:3] == b"\xef\xbb\xbf"
    try:
        # utf-8-sig is also valid plain UTF-8 and removes a BOM when present;
        # decoding as plain utf-8 first would leak U+FEFF into the first silo.
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # W2-002: not UTF-8. A lossy decode (errors="replace") would
        # silently replace undecodable bytes with U+FFFD, and the
        # UTF-8-only writer would then publish those replacement
        # characters back to disk — a permanent corruption of the
        # source file. Fail closed: skip the file instead.
        return None
    eol = detect_eol(text)
    return text.replace("\r\n", "\n"), eol, had_utf8_bom


def write_text_file(path: str, text: str, eol: str = "\n",
                    write_bom: bool = False) -> str | None:
    """Write ``text`` with the file's EOL, atomically (temp + rename).

    ``write_bom`` re-emits a UTF-8 byte-order mark when the source file
    carried one (CORE-007). New, BOM-less files stay BOM-less by default.
    Returns the text ACTUALLY written (EOL-normalised, BOM excluded from the
    returned string) so callers can store it as the "last applied" baseline —
    comparing a \\n-only silo text against a \\r\\n file would otherwise look
    like an external edit. Returns None on failure."""
    if eol != "\n":
        text = text.replace("\n", eol)
    from fastprompter.utils.path_safety import unique_temp_path
    tmp = unique_temp_path(path, "psync")
    try:
        with open(tmp, "wb") as fh:
            if write_bom:
                fh.write(b"\xef\xbb\xbf")
            fh.write(text.encode("utf-8"))
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
