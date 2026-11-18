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

import datetime
import fnmatch
import hashlib
import os
import re
import shutil
import uuid
import zlib

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


# W2-001: the identity token of a destination that was read as ABSENT. The
# publish below refuses the moment a writer creates the file in the window
# between that read and the replace, because "absent" is a precondition too.
MISSING_ON_DISK = ("<missing>", 0, 0)

# CORE-001: a destination that EXISTS but cannot be read is a different fact
# from one that is absent, and only the second is permission to create. The
# former ``except OSError: return MISSING_ON_DISK`` collapsed both, so an
# ACL-denied or locked destination satisfied the "approved as missing"
# precondition and the unconditional final gate then replaced bytes that had
# never been compared against it. UNREADABLE compares unequal to every
# identity token, including a second UNREADABLE, so both gates refuse.
UNREADABLE = ("<unreadable>", -1, -1)


def is_unreadable_identity(token) -> bool:
    """True when ``token`` is the CORE-001 unreadable-destination marker.

    Callers classify a refusal with this instead of ``token is not None``: an
    unreadable target is a write error against an unsafe path, never an
    external edit to hand to conflict resolution.
    """
    return token == UNREADABLE


def raw_identity(data: bytes):
    """The content identity of the EXACT bytes a reader consumed.

    Identity is deliberately not mtime/size: an external editor that rewrites
    the same number of bytes inside the same timestamp tick would otherwise be
    invisible, and its save would be silently overwritten.
    """
    return (hashlib.sha256(data).hexdigest(), len(data),
            zlib.crc32(data) & 0xFFFFFFFF)


def disk_identity(path: str):
    """The identity of ``path`` right now, or None when it cannot be read."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    return raw_identity(data)


def read_text_file_with_identity(path: str, max_bytes: int = DEFAULT_MAX_BYTES):
    """Read ``path`` as text AND the identity of the bytes just consumed.

    Same contract as ``read_text_file`` with a fourth value appended, and the
    identity comes from the SAME byte string the text was decoded from — one
    read, one truth, so a publisher can revalidate against exactly the state
    it accepted. The returned text is EOL-normalised, as before.
    """
    try:
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
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    eol = detect_eol(text)
    return (text.replace("\r\n", "\n"), eol, had_utf8_bom,
            raw_identity(data))


def _conflict_artifact_path(path: str) -> str | None:
    """A durable sibling path that will hold the bytes an external edit wrote.

    CORE-001: when publication cannot prove exclusive ownership across the
    final rename, the revision that was on disk must not evaporate. The copy
    goes next to the destination (same volume, so a hardlink or a fast copy is
    possible) under a dot-name that the scanner's default exclude list ignores.
    """
    try:
        directory = os.path.dirname(os.path.abspath(path))
        base = os.path.basename(path)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        token = uuid.uuid4().hex[:8]
        return os.path.join(directory, f".{base}.conflict-{stamp}-{token}.bak")
    except Exception:
        return None


def _preserve_conflict_copy(path: str) -> str | None:
    """Copy the CURRENT destination bytes to a durable artifact; return it.

    Returns None when nothing could be preserved. The write is best-effort by
    design: failing to make the safety copy must never abort the publication
    decision itself, but the caller must not claim the conflict was preserved
    unless this returned a path.
    """
    dest = _conflict_artifact_path(path)
    if dest is None:
        return None
    try:
        with open(path, "rb") as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        return dest
    except OSError:
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        return None


def compare_and_publish_text(path: str, text: str, expected_identity,
                             eol: str = "\n", write_bom: bool = False,
                             before_publish=None):
    """Publish ``text`` to ``path`` ONLY if the disk still holds what was read.

    The push worker's commit gate serializes FastPrompter's own ownership
    transitions, but it cannot serialize an external editor. A save landing
    after the read and before ``os.replace`` would be silently destroyed, so
    the destination's own state becomes part of the publication precondition.

    ``expected_identity`` is what the reader accepted — a ``raw_identity``
    token from ``disk_identity``/``read_text_file_with_identity``, or
    ``MISSING_ON_DISK`` when the destination was read as absent. ``before_publish``
    is an optional hook that runs after the identity is captured and before the
    atomic replace, which is exactly where the TOCTOU window lives; it exists
    so the revalidation can be reproduced deterministically.

    Returns ``(written_text, None)`` on success and ``(None, conflict_id)``
    when the destination no longer matches — the caller reports a conflict
    carrying the CURRENT disk content instead of overwriting it.
    ``conflict_id is UNREADABLE`` is the separate fact that the destination
    exists but could not be read: a refusal too, but not a resolvable
    conflict, so callers can classify it as an unsafe target.

    CORE-001: revalidation is now UNCONDITIONAL and runs as late as possible,
    with no Python-level work between the check and the rename. A filesystem
    without a compare-and-swap rename cannot make check-then-replace atomic, and
    this function does not claim otherwise. What it does guarantee: every
    refusal hands back a durable copy of the revision that defeated the gate
    (``_preserve_conflict_copy``), so a lost update can never be a *silent*
    lost update — the bytes survive in a ``.<name>.conflict-*.bak`` sibling.
    """
    def _current():
        # CORE-001: three distinct observations, never conflated. ABSENT is
        # established only by FileNotFoundError (or an equivalent missing-path
        # error), which is the sole precondition that authorises a create.
        # Every other OSError is UNREADABLE and fails the gate closed.
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return MISSING_ON_DISK
        except NotADirectoryError:
            # A path component is not a directory: the destination cannot be a
            # regular file, so it is not recreatable either.
            return UNREADABLE
        except OSError:
            return UNREADABLE
        return raw_identity(data)

    # A destination that is (or became) a directory cannot be published
    # to: that is a write failure, not an external edit, and must never be
    # reported as a sync conflict carrying stale on-disk bytes.
    if os.path.isdir(path):
        return None, None
    accepted = _current()
    if accepted != expected_identity:
        # CORE-001: a destination we cannot read has no readable revision to
        # preserve and is refused as an unsafe target, not reported as an
        # external edit the caller could resolve.
        if not is_unreadable_identity(accepted):
            _preserve_conflict_copy(path)
        return None, accepted
    if before_publish is not None:
        before_publish()
    # CORE-001: the final gate runs whether or not a hook was supplied, and it
    # is the last statement before the write, so the residual window is the
    # single rename syscall inside write_text_file rather than a stretch of
    # Python work the caller cannot see. A destination that became unreadable
    # between the two gates is refused here, exactly like one that changed.
    if os.path.isdir(path):
        return None, None
    final = _current()
    if final != expected_identity:
        if not is_unreadable_identity(final):
            _preserve_conflict_copy(path)
        return None, final
    written = write_text_file(path, text, eol, write_bom=write_bom)
    if written is None:
        # Write failure (OSError): not a conflict. Returning no conflict id
        # lets callers report a write error instead of clobbering the silo
        # with stale on-disk text.
        return None, None
    return written, None


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
    except OSError as exc:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        try:
            from fastprompter.core.logging import logger
            logger.warning("write_text_file failed for %s: %s", path, exc)
        except Exception:
            pass
        return None


def free_slots(mapping: dict, total: int, count: int) -> list[int]:
    """The first ``count`` slots not claimed by ``mapping``.

    ``mapping`` maps str(slot) -> relpath. Slots are allocated from the end
    of the silo list (appending) or the first free gap, newest files first —
    but to keep the mapping stable across rescans, new files simply take the
    lowest unclaimed slot at or after ``total``.
    """
    claimed = set()
    for k in mapping:
        try:
            val = int(k)
            if 0 <= val < 100:
                claimed.add(val)
        except (ValueError, TypeError):
            continue
    slots: list[int] = []
    slot = total
    while len(slots) < count:
        if slot >= 100:  # hard cap, matches MAX_SILOS_PER_CATEGORY
            break
        if slot not in claimed:
            slots.append(slot)
        slot += 1
    return slots
