"""Silo bundle engine (T-1409) — pure, Qt-free, stdlib-only.

The whole Pack feature is built on one oracle in this module::

    live text + explicit local sources -> BundlePlan -> portable Markdown -> ZIP

Nothing here imports Qt, so every rule below is provable with plain pytest and a
temp directory, which is what the ticket's ``verify:`` line asks for.

The contract this module owns:

* **Discovery** walks the Markdown for local media. It never touches the network
  and never mutates the source document; the exported snapshot is rewritten, the
  live silo is not.
* **Identity** for dedup and for the rewrite map is the canonical resolved real
  path, so the same file reached through two spellings, or reached twice, or
  present both inline and in Silo Files, is packaged exactly once.
* **Member names** are relative, sanitized and sequence-prefixed. No drive
  letters, no ``..``, no UNC prefix, no absolute ``V:\\...`` ever becomes an
  archive member name.
* **Publication** is atomic: build into a unique temp sibling, then ``os.rename``
  (which on Windows refuses to overwrite an existing target). A cancelled or
  failed pack leaves no partial archive and leaves the destination untouched.

ponytail: SHA256 is computed while streaming, so nothing is read twice, but the
digest is a manifest convenience rather than an integrity gate. Add an explicit
verify-after-publish step when a bundle ever has to be proved against tampering.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field, replace
from urllib.parse import unquote, urlsplit

from fastprompter.core import silo_index
from fastprompter.core.markdown_refs import (
    encode_destination,
    find_markdown_refs,
)
from fastprompter.utils import path_safety

logger = logging.getLogger(__name__)

# T-1411/T-1412/T-1413/T-1414: schema 5 adds fast selection bundles,
# T-1411/T-1412/T-1413/T-1414/T-1416: schema 6 adds never-block publication,
# bounded index degradation, detached media blocks, and media evidence.
SCHEMA_VERSION = 6
REUSABLE_SCHEMAS = frozenset({6})
INDEX_SCHEMA_VERSION = silo_index.INDEX_SCHEMA_VERSION

# The LOGICAL bundle identity's own version. Bump it whenever the set of facts
# folded into content_fingerprint() changes; reuse across two different
# fingerprint schemas is refused. App-version changes alone never invalidate.
# T-1417: 5 -> 6. The derived structured index left the payload, so a
# preflight fingerprint and a published fingerprint describe one payload.
FINGERPRINT_SCHEMA = 6

_LINK_PREFIX_RE = re.compile(r"(!?)\[([^\]\n]*)\]\(")
_REMOTE_URL_RE = re.compile(r"https?://[^\s)\]>\"'`]+", re.IGNORECASE)

_COMBINED_LOCAL_PATH_RE = re.compile(
    r"(?:<)?(?P<file>file:(?:/{1,3})(?:localhost/)?(?P<file_path>[a-zA-Z]:[^\s)\]>\"'`]+))(?:>)?|"
    r"(?:<)?(?P<unc>\\\\[a-zA-Z0-9_.\-]+\\[^\s)\]>\"'`]+)(?:>)?|"
    r"(?:<)?(?<![a-zA-Z0-9_])(?P<win>[a-zA-Z]:[\\/][^\s)\]>\"'`]*)(?:>)?",
    re.IGNORECASE,
)


def _get_clean_name(raw_path: str) -> str:
    p = unquote(raw_path).strip().rstrip(">").rstrip("/")
    p = p.replace("\\\\", "/").replace("\\", "/")
    parts = [part for part in p.split("/") if part and not part.endswith(":")]
    return parts[-1] if parts else ""


# ---------------------------------------------------------------------------
# Residual local-path sanitization (T-1417).
#
# The previous token stopped at whitespace, so it redacted only the FIRST
# segment of a path that contains spaces:
#     C:\Users\Name\My Documents\secret file.txt
#       -> [local path omitted: My] Documents\secret file.txt
# The drive letter disappeared while every folder and file after it survived,
# which is not sanitization. Widening that charclass to ``.*`` would instead eat
# the surrounding prose, so the boundary is resolved by CONTEXT instead, in
# priority order:
#
#   A. a Markdown target, whose exact span the canonical parser already knows
#      and which is therefore one token even when it holds spaces;
#   B. an angle-bracketed or quoted path, consumed to its matching delimiter;
#   C. a file:// URL;
#   D. a bare Windows/UNC path, bounded by structure and then trimmed of any
#      trailing prose words.
#
# When the exact end cannot be proven the transform errs toward redaction:
# over-redacting a path is safe, under-redacting one is the leak this ticket
# exists to close.
# ---------------------------------------------------------------------------

_PATH_START_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"file:(?:/{1,3}|//)(?=[A-Za-z0-9_.\-])"
    r"|\\\\[A-Za-z0-9_.\-]+"
    r"|[A-Za-z]:[\\/]"
    r")",
    re.IGNORECASE,
)

_PATH_STOP_CHARS = "\n\r\"'<>)]"
_PATH_TAIL_EXTS = re.compile(r"\.[A-Za-z0-9]{1,8}$")
_PROSE_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’]*$")

_DELIMITERS = {"<": ">", '"': '"', "'": "'"}


def _ends_a_filename(token: str) -> bool:
    """True when ``token`` finishes on a filename, not mid-directory.

    Only a finished filename proves that the words after it are prose. A token
    like ``C:\\Users\\Alice\\Secret`` may just as easily be followed by a
    directory name, so trimming there would leave half a path behind.
    """
    return bool(_PATH_TAIL_EXTS.search(token))


def _cut_trailing_prose(raw: str) -> str:
    """Drop trailing English words that followed an unquoted path.

    ``C:\\Users\\Name\\file.txt for details`` must redact the path and keep the
    sentence. The trim is only accepted when the token in front of the words ends
    on a filename extension; otherwise the words are part of a directory name and
    stay, because over-redacting is the safe side.
    """
    tokens = list(re.finditer(r"\S+", raw))
    cut = None
    i = len(tokens) - 1
    while i >= 0 and _PROSE_WORD_RE.match(tokens[i].group(0)):
        cut = tokens[i].start()
        i -= 1
    if cut is not None and i >= 0 and _ends_a_filename(tokens[i].group(0)):
        return raw[:cut]
    return raw


def _consume_local_path(text: str, start: int, limit: int) -> tuple[str, str]:
    """Return ``(path_text, trailing_punctuation)`` for the token at ``start``."""
    closer = _DELIMITERS.get(text[start - 1]) if start else None
    if closer:
        # A delimiter in front PROVES the end; nothing is guessed.
        k = text.find(closer, start)
        return text[start:k if k != -1 else len(text)], ""

    k = start
    n = min(len(text), limit)
    while k < n and text[k] not in _PATH_STOP_CHARS:
        k += 1
    raw = text[start:k]

    trailing = ""
    while raw and raw[-1] in ".,;:!?":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    return _cut_trailing_prose(raw), trailing


def _omission(raw: str) -> str:
    clean_name = _get_clean_name(raw)
    if clean_name:
        return f"[local path omitted: {clean_name}]"
    return "[local path omitted]"


def sanitize_residual_local_paths(text: str) -> tuple[str, int]:
    """Deterministically redact absolute workstation paths in generated share text.

    Leaves remote URLs (https://, http://) and safe relative paths intact, and
    preserves surrounding prose without reformatting it.
    """
    if not text:
        return text, 0

    # Spans whose boundary is already proven: a remote URL is never ours to
    # touch, and a Markdown target is atomic because the canonical parser
    # already resolved where it ends.
    spans: list[tuple[int, int, str]] = [
        (m.start(), m.end(), "keep") for m in _REMOTE_URL_RE.finditer(text)
    ]
    for ref in find_markdown_refs(text):
        start, end = ref.target_span
        if start is None or end is None or end <= start:
            continue
        if _classify_target(ref.clean_target) in ("file", "path"):
            spans.append((start, end, "local"))
    spans.sort(key=lambda s: (s[0], s[1]))

    out: list[str] = []
    count = 0
    pos = 0
    idx = 0
    n = len(text)

    while pos < n:
        span = spans[idx] if idx < len(spans) else None

        if span is not None and span[0] <= pos < span[1]:
            _, end, kind = span
            if kind == "keep":
                out.append(text[pos:end])
            else:
                out.append(_omission(text[pos:end]))
                count += 1
            pos = end
            idx += 1
            continue

        if span is not None and span[0] < pos:
            idx += 1
            continue

        # A bare token must never run across a proven remote URL.
        limit = n
        for s_start, _s_end, s_kind in spans[idx:]:
            if s_start > pos:
                if s_kind == "keep":
                    limit = s_start
                break

        match = _PATH_START_RE.search(text, pos, limit)
        if not match:
            out.append(text[pos:])
            break

        out.append(text[pos:match.start()])
        raw, trailing = _consume_local_path(text, match.start(), limit)
        out.append(_omission(raw))
        if trailing:
            out.append(trailing)
        count += 1
        pos = match.start() + len(raw) + len(trailing)

    return "".join(out), count


# ---------------------------------------------------------------------------
# Media classification — ONE authority.
#
# The repo previously had two divergent image sets (file_container._IMAGE_EXTS
# with .ico, image_viewer.IMAGE_SUFFIXES without it) and no video/audio set at
# all. Both now re-point here so a bundle, a thumbnail and a preview can never
# disagree about what counts as media.
# ---------------------------------------------------------------------------

IMAGE_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".ico", ".tif", ".tiff", ".svg", ".avif",
})
VIDEO_EXTS = frozenset({
    ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v",
})
AUDIO_EXTS = frozenset({
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus",
})

MEDIA_TYPES = ("image", "video", "audio")

# Sub-folders of a silo folder that are never part of a bundle. `exports/` is
# where bundles land, so without this a pack would nest yesterday's archives
# inside today's.
EXCLUDED_SILO_DIRS = ("exports",)


def classify_media(path) -> str | None:
    """``"image"`` / ``"video"`` / ``"audio"`` / None (not media)."""
    # splitext() is wrong for a leading-dot name: it reports "..png" as name
    # with NO extension. Windows accepts that filename, so the extension is
    # taken from the last dot in the basename directly.
    name = os.path.basename(str(path))
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot > 0 else ""
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


# ---------------------------------------------------------------------------
# Markdown reference discovery
# ---------------------------------------------------------------------------

# A link or image target, tolerating one level of balanced parentheses so a
# literal path is read whole rather than truncated at the first ')'.
_LINK_RE = re.compile(r"(!?)\[([^\]\n]*)\]\(\s*((?:[^()\s]|\([^()\s]*\))*)\s*\)")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_REMOTE_SCHEMES = frozenset({"http", "https", "mailto", "ftp", "ftps", "data", "tel"})
_WIN_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class LocalRef:
    """One Markdown target, already classified and (for local ones) resolved."""

    raw: str                 # the target exactly as written in the document
    path: str | None         # absolute local path, or None when remote/unknown
    kind: str                # "file" | "path" | "relative" | "remote" | "skip"
    is_image: bool           # came from ![alt](target)
    doc_index: int           # occurrence order across the whole document
    link_span: tuple         # (start, end) of the whole ![alt](target) / [a](b)
    target_span: tuple       # (start, end) of just the target text


def _file_url_to_path(raw: str) -> str:
    s = raw.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    parts = urlsplit(s)
    path = unquote(parts.path)
    if parts.netloc and parts.netloc.lower() not in ("", "localhost"):
        return "\\\\" + parts.netloc + path.replace("/", "\\")
    # file:///V:/x.png -> /V:/x.png -> V:/x.png ; an absolute drive path has a
    # leading slash the URL grammar requires but Windows does not.
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    resolved = path.replace("/", os.sep) if os.sep != "/" else path
    if parts.fragment and not os.path.exists(resolved):
        cand = unquote(parts.path) + "#" + unquote(parts.fragment)
        if re.match(r"^/[A-Za-z]:", cand):
            cand = cand[1:]
        cand = cand.replace("/", os.sep) if os.sep != "/" else cand
        if os.path.exists(cand):
            return cand
    return resolved


def _classify_target(target: str) -> str:
    t = target.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    if not t or t.startswith("#"):
        return "skip"
    # A Windows drive letter is shaped exactly like a URL scheme ("V:/x"), so
    # the drive test has to come FIRST or every absolute Windows path the user
    # pastes is mistaken for an unknown scheme and skipped.
    if t.startswith("\\\\") or _WIN_ABS_RE.match(t) or t.startswith("/"):
        return "path"
    if t.lower().startswith("file:"):
        return "file"
    m = _SCHEME_RE.match(t)
    if m:
        scheme = m.group(0)[:-1].lower()
        return "remote" if scheme in _REMOTE_SCHEMES else "skip"
    return "relative"


def _resolve_target(target: str, base_dir: str | None):
    """(kind, resolved_path_or_None). A relative target needs a real base."""
    t = target.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    kind = _classify_target(t)
    if kind == "file":
        return kind, _file_url_to_path(t)
    if kind == "path":
        return kind, t
    if kind == "relative":
        if not base_dir:
            return kind, None
        return kind, os.path.normpath(os.path.join(base_dir, t))
    return kind, None


def find_local_refs(text: str, base_dir: str | None = None):
    """Every Markdown target in ``text``, in document order.

    ``base_dir`` is the folder a relative target is resolved against; without
    it a relative ref stays unresolved rather than being guessed against the
    process CWD.
    """
    refs = []
    for m in find_markdown_refs(text):
        target_to_resolve = m.raw_target if m.raw_target.strip().lstrip("<").lower().startswith("file:") else m.clean_target
        kind, path = _resolve_target(target_to_resolve, base_dir)
        refs.append(LocalRef(
            raw=m.raw_target,
            path=path,
            kind=kind,
            is_image=m.is_image,
            doc_index=m.doc_index,
            link_span=m.link_span,
            target_span=m.target_span,
        ))
    return refs


# ---------------------------------------------------------------------------
# Added-time authority
# ---------------------------------------------------------------------------

# FastPrompter's own pastes are named paste-YYYYMMDD_HHMMSS.png, and the
# clipboard screenshot tool uses the same stamp. Recognised, never invented.
_STAMP_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})(?!\d)")


def _stamp_from_name(name: str) -> float | None:
    m = _STAMP_RE.search(os.path.basename(name))
    if not m:
        return None
    try:
        stamp = _dt.datetime(*(int(g) for g in m.groups()), tzinfo=None)
    except ValueError:
        return None
    return stamp.timestamp()


def added_at(path: str, doc_index: int, meta: dict | None = None):
    """(epoch, source) for one media file.

    Rungs, in the order the ticket names them:
      1. the silo's own persisted first-seen record (exact for anything
         FastPrompter inserted itself),
      2. a timestamp encoded in a recognised clipboard/paste filename,
      3. Windows creation/birth time where the filesystem reports one,
      4. file mtime,
      5. document occurrence order — reported as 0.0 so the dialog can still
         sort those deterministically without inventing a date.

    The chosen rung is returned alongside the value so the manifest can state
    where the number came from instead of implying precision it does not have.
    """
    key = _canonical(path)
    if meta:
        recorded = meta.get(key)
        if recorded is not None:
            try:
                return float(recorded), "silo_metadata"
            except (TypeError, ValueError):
                pass
    stamp = _stamp_from_name(path)
    if stamp is not None:
        return stamp, "filename_stamp"
    try:
        stat = os.stat(path)
    except OSError:
        return 0.0, "document_order"
    birth = getattr(stat, "st_birthtime", None) or getattr(stat, "st_ctime", None)
    if birth:
        return float(birth), "file_birthtime"
    return float(stat.st_mtime), "file_mtime"


def _canonical(path: str) -> str:
    """The dedup identity: realpath, normcased, normalized separators."""
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(path))


# ---------------------------------------------------------------------------
# Silo folder listing
# ---------------------------------------------------------------------------

def _is_reparse_or_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
        st = os.lstat(path)
        import stat
        attrs = getattr(st, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if attrs & reparse:
            return True
    except (OSError, ValueError):
        return True
    return False


def list_silo_files(silo_dir: str, include_attachments: bool = False) -> list[str]:
    """Recursively discover regular files in a silo folder, as absolute paths.

    Traverses subdirectories under silo_dir while strictly excluding
    symlinks, junctions, reparse points, and EXCLUDED_SILO_DIRS ('exports/').
    """
    out = []
    if not silo_dir or not os.path.isdir(silo_dir) or _is_reparse_or_link(silo_dir):
        return out
    silo_real = os.path.normcase(os.path.realpath(silo_dir))

    for root, dirs, files in os.walk(silo_dir, topdown=True, followlinks=False):
        try:
            root_real = os.path.normcase(os.path.realpath(root))
            if os.path.commonpath([silo_real, root_real]) != silo_real:
                dirs.clear()
                continue
        except (OSError, ValueError):
            dirs.clear()
            continue

        pruned_dirs = []
        for d in sorted(dirs, key=str.lower):
            if d.lower() in EXCLUDED_SILO_DIRS:
                continue
            d_full = os.path.join(root, d)
            if _is_reparse_or_link(d_full):
                continue
            pruned_dirs.append(d)
        dirs[:] = pruned_dirs

        for name in sorted(files, key=str.lower):
            full = os.path.join(root, name)
            if _is_reparse_or_link(full):
                continue
            if not os.path.isfile(full):
                continue
            media = classify_media(full)
            if media is None and not include_attachments:
                continue
            out.append(full)
    return out


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BundleItem:
    source: str          # canonical resolved path
    display_name: str    # original filename, for the manifest and the dialog
    member: str          # archive member name, e.g. "media/001_shot.png"
    media_type: str      # "image" | "video" | "audio" | "attachment"
    size: int
    added_epoch: float
    added_source: str
    doc_index: int
    origin: str          # "inline" | "silo_files" | "both"
    available: bool
    silo_relative_path: str | None = None


@dataclass(frozen=True)
class BundlePlan:
    """Everything a pack needs, frozen at click time (T-1409 section 39)."""

    archive_name: str            # base name; the no-clobber suffix is added at write
    display_title: str
    category: str
    target_dir: str
    text_member: str | None      # None when the user unchecked the text
    text_body: str | None        # the portable snapshot; never the live text
    items: tuple = ()            # tuple[BundleItem]
    manifest: dict = field(default_factory=dict)
    origin_text: str = ""        # byte-identical source the snapshot came from
    index_member: str | None = "silo.index.json"
    index_data: dict | None = None
    readme_member: str | None = "README.txt"
    readme_body: str | None = None
    dimensions: dict = field(default_factory=dict)

    def member_for(self, canonical: str) -> str | None:
        for item in self.items:
            if item.source == canonical:
                return item.member
        return None


@dataclass(frozen=True)
class BundleResult:
    zip_path: str | None
    items: tuple = ()
    missing: tuple = ()
    cancelled: bool = False
    error: str = ""
    # T-1411: facts the history needs, all measured by the writer itself.
    fingerprint: str = ""
    hashes: dict = field(default_factory=dict)      # member -> sha256
    signatures: dict = field(default_factory=dict)  # member -> stat signature
    archive_size: int = 0
    archive_mtime_ns: int = 0
    bundle_status: str = "complete"  # "complete" | "partial" | "degraded"
    index_status: str = "full"        # "full" | "degraded" | "unavailable"
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Readable filename codec (T-1411)
#
# A DISPLAY title ("FastPrompter: (Evening 03 Oct - 17:39)") and a FILESYSTEM
# stem ("FastPrompter - (Evening 03 Oct - 17-39)") are different things. The
# strict validate_component() is a reject-or-accept gate for names a user
# types as names; applied to a human heading it rejected the whole title on
# one ':' and every such silo became "silo_bundle_...". This codec degrades
# character by character instead, and never leaks a path separator.
# ---------------------------------------------------------------------------

_STEM_COLON_SPACED = re.compile(r"\s*:\s+")
_STEM_SEPARATORS = re.compile(r"[/\\|]")
_STEM_DROP = re.compile(r"[?*<>\x00-\x1f\x7f]")
_STEM_DASH_RUN = re.compile(r"-{2,}")
_STEM_SPACE_RUN = re.compile(r"\s+")
_STEM_MAX = 80


def bundle_stem(title: str, fallback: str = "silo", max_len: int = _STEM_MAX) -> str:
    """A readable, bounded, Windows-safe stem derived from ``title``.

    ``": "`` reads as a separator (``" - "``), a bare ``':'`` becomes ``'-'``
    (so ``17:39`` stays legible as ``17-39``), path separators become
    ``'-'``, ``'"'`` becomes ``"'"``, and ``? * < >`` plus control characters
    are dropped. Unicode and emoji are kept. Trailing dots/spaces are trimmed
    (Windows strips them silently) and a reserved device name is prefixed.
    """
    text = unicodedata.normalize("NFC", str(title or ""))
    text = _STEM_COLON_SPACED.sub(" - ", text)
    text = text.replace(":", "-")
    text = _STEM_SEPARATORS.sub("-", text)
    text = text.replace('"', "'")
    text = _STEM_DROP.sub("", text)
    text = _STEM_SPACE_RUN.sub(" ", text)
    text = _STEM_DASH_RUN.sub("-", text)
    text = re.sub(r"(?:\s*-\s*){2,}", " - ", text)
    text = text.strip(" .-_")
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .-_")
    if not text:
        return fallback
    if path_safety._RESERVED_RE.match(text):
        text = "_" + text
    return text


def _safe_title(title: str) -> str:
    return bundle_stem(title, fallback="silo")


def archive_basename(title: str, now: _dt.datetime) -> str:
    return f"{_safe_title(title)}_bundle_{now:%Y%m%d_%H%M%S}.zip"


def _assign_members(entries, folder: str, name_map: dict[str, str] | None = None) -> dict:
    """canonical path -> member name.

    The sequence prefix is what keeps two different files that share a basename
    distinct: ``image.png`` from two folders becomes ``media/001_image.png`` and
    ``media/002_image.png`` instead of the second overwriting the first.
    """
    mapping = {}
    for seq, canonical in enumerate(entries, start=1):
        raw_name = (name_map.get(canonical) if name_map else None) or os.path.basename(canonical)
        component, _ = path_safety.fs_component(
            raw_name or "file", fallback="file")
        mapping[canonical] = f"{folder}/{seq:03d}_{component}"
    return mapping


def portable_markdown(
    text: str,
    refs,
    members: dict,
    hide_local_paths: bool,
    omitted_refs_out: list[dict] | None = None,
    privacy_stats_out: dict | None = None,
) -> str:
    """Rewrite only the local refs whose file is in ``members``.

    Applied back-to-front so earlier spans stay valid. A local ref that is NOT
    in the bundle is either hidden behind a neutral marker (share-safe default)
    or left exactly as written. Remote targets are never touched: this feature
    does not download anything, so an ``https://`` image stays an https image.
    """
    if not hide_local_paths:
        return text
    pieces = []
    cursor = 0
    rewritten_count = 0
    omitted_count = 0

    for ref in refs:
        if ref.kind in ("remote", "skip"):
            continue
        canonical = _canonical(ref.path) if ref.path else None
        member = members.get(canonical) if canonical else None
        if member:
            start, end = ref.target_span
            replacement = encode_destination(member)
            rewritten_count += 1
        else:
            if ref.kind not in ("file", "path", "relative"):
                continue
            raw_name = os.path.basename(ref.path or ref.raw) or "file"
            clean_name = raw_name.strip().rstrip(">").rstrip("/")
            if clean_name.endswith(">"):
                clean_name = clean_name[:-1]
            if not clean_name:
                clean_name = "file"

            start, end = ref.link_span
            omitted_count += 1
            if ref.is_image:
                replacement = f"[local media omitted: {clean_name}]"
                kind = "media"
            else:
                link_slice = text[start:end]
                m = _LINK_PREFIX_RE.match(link_slice)
                label = m.group(2) if m else ""
                if label:
                    replacement = f"{label} [local file omitted: {clean_name}]"
                else:
                    replacement = f"[local file omitted: {clean_name}]"
                kind = "attachment"

            if omitted_refs_out is not None:
                omitted_refs_out.append({
                    "display_name": clean_name,
                    "kind": kind,
                    "reason": "not_included",
                })

        if start < cursor:          # a nested/overlapping match; first wins
            continue
        pieces.append(text[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(text[cursor:])
    intermediate = "".join(pieces)

    final_text, redacted_residual = sanitize_residual_local_paths(intermediate)

    if privacy_stats_out is not None:
        privacy_stats_out["local_refs_rewritten"] = rewritten_count
        privacy_stats_out["local_refs_omitted"] = omitted_count
        privacy_stats_out["residual_paths_redacted"] = redacted_residual

    return final_text


def is_blank_selection(text: str) -> bool:
    """Return True if text is empty or whitespace only."""
    return not bool(text and text.strip())


def expand_selection_token_boundaries(text: str, start: int, end: int) -> tuple[int, int]:
    """If [start, end) intersects any image or local media link token, expand to contain the full token."""
    if not text or start >= end:
        return start, end
    refs = find_markdown_refs(text)
    new_start = start
    new_end = end
    for ref in refs:
        l_start, l_end = ref.link_span
        if max(start, l_start) < min(end, l_end):
            clean = ref.clean_target
            is_media = ref.is_image or (classify_media(clean) is not None)
            if clean.startswith(("http://", "https://", "mailto:", "ftp://")):
                is_media = False
            if is_media:
                new_start = min(new_start, l_start)
                new_end = max(new_end, l_end)
    return new_start, new_end


_SEL_CLEAN_IMG = re.compile(r"!\[[^\]\n]*\]\(\s*(?:[^()\s]|\([^()\s]*\))*\s*\)")
_SEL_CLEAN_LNK = re.compile(r"\[([^\]\n]*)\]\(\s*(?:[^()\s]|\([^()\s]*\))*\s*\)")
_SEL_CLEAN_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|[•⁃‣\-\*\+]\s+|\d{1,4}[.)]\s+)")
_SEL_CLEAN_PRIORITY = re.compile(r"(?i)\b(P[0-3])(?::|\b)")


def extract_selection_words(text: str, fallback_title: str = "") -> list[str]:
    """Extract up to 3 meaningful words from selection for fast naming.

    Strips Markdown headings, bullets, image tokens, priority markers, punctuation.
    Unicode-aware (keeps Cyrillic, accented characters).
    Falls back to silo title words, then ['selection'].
    """
    clean_lines = []
    for line in text.splitlines():
        cur_line = _SEL_CLEAN_PREFIX.sub("", line)
        cur_line = _SEL_CLEAN_IMG.sub("", cur_line)
        cur_line = _SEL_CLEAN_LNK.sub(r"\1", cur_line)
        cur_line = _SEL_CLEAN_PRIORITY.sub("", cur_line)
        clean_lines.append(cur_line)
    cleaned = " ".join(clean_lines)

    # Unicode word tokens containing at least one alphabetic character
    raw_tokens = re.findall(r"[^\W\d_]+[\w-]*|\w+", cleaned, re.UNICODE)
    meaningful = [t for t in raw_tokens if any(c.isalpha() for c in t)]

    if not meaningful and fallback_title:
        fb_tokens = re.findall(r"[^\W\d_]+[\w-]*|\w+", fallback_title, re.UNICODE)
        meaningful = [t for t in fb_tokens if any(c.isalpha() for c in t)]

    if not meaningful:
        return ["selection"]
    return meaningful[:3]


def fast_selection_basename(words: list[str]) -> str:
    """Create fast selection bundle basename: fast_<words>_bundle.zip."""
    raw_stem = "_".join(words[:3]) if words else "selection"
    stem = bundle_stem(raw_stem, fallback="selection", max_len=60)
    return f"fast_{stem}_bundle.zip"


_BUILD_PROVENANCE_CACHE: dict | None = None


def get_build_provenance(app_version: str = "") -> dict:
    """Return compact technical build provenance (cached, zero machine paths)."""
    global _BUILD_PROVENANCE_CACHE
    if _BUILD_PROVENANCE_CACHE is not None:
        res = dict(_BUILD_PROVENANCE_CACHE)
        if app_version and not res.get("app_version"):
            res["app_version"] = app_version
        return res

    import subprocess
    import sys

    version = app_version or ""
    if not version:
        try:
            cand = os.path.join(os.path.dirname(__file__), "..", "..", "..", "VERSION")
            if os.path.isfile(cand):
                with open(cand, encoding="utf-8") as f:
                    version = f.read().strip()
        except Exception:
            pass

    channel = "release" if getattr(sys, "frozen", False) else "development"
    rev = None
    dirty = None

    if not getattr(sys, "frozen", False):
        try:
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if r.returncode == 0:
                rev = r.stdout.strip()
            s = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if s.returncode == 0:
                dirty = bool(s.stdout.strip())
        except Exception:
            pass

    _BUILD_PROVENANCE_CACHE = {
        "app_version": version,
        "source_revision": rev,
        "channel": channel,
        "working_tree_dirty": dirty,
    }
    return dict(_BUILD_PROVENANCE_CACHE)


def _share_safe(value) -> str:
    """Redact absolute workstation paths from ONE user-derived string.

    T-1417: this is the single privacy boundary applied to every generated
    share-safe surface. It runs per FIELD, before serialization -- never as a
    regex over the JSON text, which would corrupt the syntax it edits.
    """
    if not value:
        return ""
    cleaned, _ = sanitize_residual_local_paths(str(value))
    return cleaned


def _build_readme(*, title: str, category: str, created_iso: str,
                  text_member: str | None, index_member: str,
                  req_count: int, group_count: int,
                  media_count: int, missing_count: int,
                  bundle_kind: str = "silo_bundle",
                  index_status: str = "full") -> str:
    header = (
        "FastPrompter Selection Bundle"
        if bundle_kind == "selection_bundle"
        else "FastPrompter Silo Bundle"
    )
    lines = [
        header,
        "=" * len(header),
        f"Title: {_share_safe(title) or 'silo'}",
    ]
    category = _share_safe(category)
    if category:
        lines.append(f"Category: {category}")
    if bundle_kind == "selection_bundle":
        lines.append("Scope: selected fragment")
    lines.append(f"Created: {created_iso}")
    lines.append("")
    lines.append("This bundle is self-contained; paths inside the Markdown are relative to this archive.")
    lines.append("")
    lines.append("Start here:")
    if index_status == "full":
        lines.append(f"1. Read {index_member} for structured requirements and media links.")
    elif index_status == "degraded":
        lines.append(f"1. Read {index_member} (note: structured index degraded; read Markdown source directly for full context).")
    else:
        lines.append("1. Structured index unavailable. Read the Markdown source directly.")

    if text_member:
        lines.append(f"2. Read {text_member} for full source context.")
    else:
        lines.append("2. (No Markdown document included in media-only bundle).")
    lines.append("3. Resolve media/... members referenced by requirement IDs.")
    lines.append("4. Read manifest.json for hashes and bundle metadata.")
    lines.append("")
    lines.append("Counts:")
    lines.append(f"  requirements: {req_count}")
    lines.append(f"  groups: {group_count}")
    lines.append(f"  media: {media_count}")
    lines.append(f"  missing: {missing_count}")
    return "\n".join(lines) + "\n"


def plan_bundle(*, text: str, title: str, target_dir: str,
                silo_dir: str | None = None, base_dir: str | None = None,
                include_text: bool = True, include_silo_media: bool = True,
                include_attachments: bool = False, hide_local_paths: bool = True,
                media_only: bool = False, category: str = "",
                app_version: str = "", silo_media_meta: dict | None = None,
                excluded=(), now: _dt.datetime | None = None,
                dimensions: dict | None = None,
                bundle_kind: str = "silo_bundle",
                scope: str = "full",
                custom_archive_name: str | None = None,
                custom_text_member: str | None = None,
                source_line_start: int = 1,
                source_line_end: int = 1) -> BundlePlan:
    """Build the immutable plan for one pack. Pure: no filesystem writes.

    ``media_only`` drops the Markdown snapshot entirely — the right-click
    shortcut, and the case where the user unchecked the text in the dialog.
    """
    now = now or _dt.datetime.now()
    include_text = include_text and not media_only
    # T-1417: ONE privacy boundary, taken at the earliest point where a
    # user-derived string can become a generated artifact. The title reaches
    # far more than the manifest -- it also mints the ARCHIVE NAME and the
    # Markdown MEMBER NAME, so sanitizing it only at the manifest would still
    # publish "C-Users-Alice-Secret Project.md" as an archive member. The live
    # document is untouched: origin_text keeps the operator's bytes verbatim.
    title = _share_safe(title)
    category = _share_safe(category)
    refs = find_local_refs(text, base_dir or silo_dir)

    # candidate canonical path -> working record, in first-seen order
    found: dict = {}
    order: list = []
    silo_rel_map: dict[str, str] = {}

    def note(canonical, display, media_type, doc_index, origin):
        rec = found.get(canonical)
        if rec is None:
            found[canonical] = {
                "display": display, "type": media_type,
                "doc_index": doc_index, "origins": {origin},
            }
            order.append(canonical)
            return
        rec["origins"].add(origin)
        if origin == "inline" and doc_index < rec["doc_index"]:
            rec["doc_index"] = doc_index

    for ref in refs:
        if ref.kind not in ("file", "path", "relative") or not ref.path:
            continue
        media_type = classify_media(ref.path)
        if media_type is None:
            continue
        note(_canonical(ref.path), os.path.basename(ref.path), media_type,
             ref.doc_index, "inline")

    if include_silo_media and silo_dir:
        for full in list_silo_files(silo_dir, include_attachments=include_attachments):
            media_type = classify_media(full)
            c_path = _canonical(full)
            note(c_path, os.path.basename(full),
                 media_type or "attachment", len(order), "silo_files")
            try:
                rel = os.path.relpath(full, silo_dir).replace("\\", "/")
                if not rel.startswith(".."):
                    silo_rel_map[c_path] = rel
            except (ValueError, OSError):
                pass

    if excluded:
        # An explicit per-file deselection (the dialog's unchecked rows) drops
        # the payload. The reference in the exported Markdown then follows the
        # share-safe policy instead of pointing at a member that is not there.
        dropped = {_canonical(p) for p in excluded}
        order = [c for c in order if c not in dropped]
    media_canon = [c for c in order if found[c]["type"] != "attachment"]
    attachment_canon = [c for c in order if found[c]["type"] == "attachment"]
    name_map = {c: found[c]["display"] for c in order}
    members = {}
    members.update(_assign_members(media_canon, "media", name_map))
    members.update(_assign_members(attachment_canon, "attachments", name_map))

    items = []
    for canonical in order:
        rec = found[canonical]
        available = os.path.isfile(canonical)
        size = os.path.getsize(canonical) if available else 0
        epoch, source = (0.0, "document_order") if not available else added_at(
            canonical, rec["doc_index"], silo_media_meta)
        items.append(BundleItem(
            source=canonical,
            display_name=rec["display"],
            member=members[canonical],
            media_type=rec["type"],
            size=size,
            added_epoch=epoch,
            added_source=source,
            doc_index=rec["doc_index"],
            origin=("both" if len(rec["origins"]) > 1
                    else next(iter(rec["origins"]))),
            available=available,
            silo_relative_path=silo_rel_map.get(canonical),
        ))

    text_member = None
    text_body = None
    omitted_local_refs: list[dict] = []
    privacy_stats: dict = {
        "local_refs_rewritten": 0,
        "local_refs_omitted": 0,
        "residual_paths_redacted": 0,
    }
    if include_text:
        text_member = custom_text_member or f"{_safe_title(title)}.md"
        text_body = portable_markdown(
            text, refs, members, hide_local_paths,
            omitted_refs_out=omitted_local_refs,
            privacy_stats_out=privacy_stats,
        )

    # T-1417: the plan is INTENT, not structured-projection authority. Building
    # the index here made planning fail-open only one step too late: a parser
    # error escaped plan_bundle(), write_bundle() never ran, and "Pack With
    # Options" could not even open. The structured projection is a PUBLICATION
    # fact and is built, validated and degraded in write_bundle() alone.
    index_member = "silo.index.json"
    index_data = None

    # Build README sidecar
    readme_member = "README.txt"
    created_iso = _dt.datetime.fromtimestamp(now.timestamp()).isoformat(timespec="seconds")
    valid_media = {i.member for i in items if i.member.startswith("media/") and i.available}
    missing_count = sum(1 for i in items if not i.available)
    readme_body = _build_readme(
        title=title,
        category=category,
        created_iso=created_iso,
        text_member=text_member,
        index_member=index_member,
        req_count=0,
        group_count=0,
        media_count=len(valid_media),
        missing_count=missing_count,
        bundle_kind=bundle_kind,
        index_status="unavailable",
    )

    plan = BundlePlan(
        archive_name=custom_archive_name or archive_basename(title, now),
        display_title=title or "",
        category=category,
        target_dir=target_dir,
        text_member=text_member,
        text_body=text_body,
        items=tuple(items),
        manifest={
            "schema_version": SCHEMA_VERSION,
            "created_at": created_iso,
            "app_version": app_version,
            "category": category,
            "silo_title": title or "",
            "text_included": bool(text_member),
            "media_only": bool(media_only),
            "portable_paths": bool(hide_local_paths),
            "attachments_included": bool(include_attachments),
            "index_member": index_member,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "requirement_count": 0,
            "group_count": 0,
            "scoped_media_count": len(valid_media),
            "unscoped_media_count": 0,
            "bundle_kind": bundle_kind,
            "scope": scope,
            "bundle_status": "complete" if not missing_count else "partial",
            "index_status": "pending",
            "canonical_source": text_member,
            "warnings": [],
            "omitted_local_refs": omitted_local_refs,
            "privacy": privacy_stats,
            "capabilities": [
                "share_safe_paths",
                "detached_media_blocks",
                "media_evidence",
                "degraded_index_fallback",
            ],
            "source": {
                "kind": scope,
                "silo_title": title or "",
                "category": category or "",
                "line_start": source_line_start,
                "line_end": source_line_end if source_line_end > 1 else max(1, len(text.splitlines())),
            },
            "build": get_build_provenance(app_version),
        },
        origin_text=text,
        index_member=index_member,
        index_data=index_data,
        readme_member=readme_member,
        readme_body=readme_body,
        dimensions=dict(dimensions or {}),
    )
    return replace(plan, manifest=_build_manifest(plan))


def plan_selection_bundle(
    *,
    selected_text: str,
    title: str,
    target_dir: str,
    silo_dir: str | None = None,
    base_dir: str | None = None,
    category: str = "",
    app_version: str = "",
    silo_media_meta: dict | None = None,
    now: _dt.datetime | None = None,
    dimensions: dict | None = None,
    line_start: int = 1,
    line_end: int = 1,
) -> BundlePlan:
    """Build the immutable plan for a Fast Selection Bundle (T-1414)."""
    words = extract_selection_words(selected_text, fallback_title=title)
    archive_name = fast_selection_basename(words)
    raw_stem = "_".join(words[:3]) if words else "selection"
    stem = bundle_stem(raw_stem, fallback="selection", max_len=60)
    text_member = f"fast_{stem}.md"

    return plan_bundle(
        text=selected_text,
        title=title,
        target_dir=target_dir,
        silo_dir=silo_dir,
        base_dir=base_dir,
        include_text=True,
        include_silo_media=False,
        include_attachments=False,
        hide_local_paths=True,
        media_only=False,
        category=category,
        app_version=app_version,
        silo_media_meta=silo_media_meta,
        now=now,
        dimensions=dimensions,
        bundle_kind="selection_bundle",
        scope="selection",
        custom_archive_name=archive_name,
        custom_text_member=text_member,
        source_line_start=line_start,
        source_line_end=line_end,
    )


# T-1417: capability flags are FINAL-OUTPUT FACTS, not engine potential. An
# archive that shipped no silo.index.json must not advertise structured
# requirements and send a receiving agent looking for a file that is not there.
def _bundle_capabilities(index_data: dict | None) -> dict:
    has_index = bool(index_data)
    return {
        "portable_markdown": True,
        "structured_requirements": has_index,
        "reverse_media_links": has_index,
        "member_hashes": True,
        "recursive_silo_media": True,
        "share_safe_paths": True,
        "detached_media_blocks": has_index,
        "media_evidence": bool(has_index and (index_data or {}).get("media_evidence")),
        # ENGINE capability, not a bundle fact: the engine can degrade, whether
        # or not THIS archive did.
        "degraded_index_fallback": True,
    }


def _build_manifest(plan: BundlePlan) -> dict:
    manifest = dict(plan.manifest)

    # Reverse mapping: member -> linked requirements
    member_to_reqs: dict[str, list[str]] = {}
    if plan.index_data and "requirements" in plan.index_data:
        for req in plan.index_data["requirements"]:
            req_id = req.get("id")
            for m in req.get("media", []):
                member_to_reqs.setdefault(m, []).append(req_id)
            for m in req.get("missing_media", []):
                member_to_reqs.setdefault(m, []).append(req_id)

    dims = plan.dimensions or {}
    items_list = []
    for item in plan.items:
        entry = {
            "member": item.member,
            "display_name": item.display_name,
            "media_type": item.media_type,
            "size": item.size,
            "added_at": (None if item.added_epoch <= 0
                         else _dt.datetime.fromtimestamp(
                             item.added_epoch).isoformat(timespec="seconds")),
            "added_source": item.added_source,
            "origin": item.origin,
            "status": "included" if item.available else "missing",
            "linked_requirements": member_to_reqs.get(item.member, []),
        }
        if item.silo_relative_path:
            entry["silo_relative_path"] = item.silo_relative_path
        dim = dims.get(item.source)
        if dim and isinstance(dim, dict):
            entry["width"] = dim.get("width")
            entry["height"] = dim.get("height")
        else:
            entry["width"] = None
            entry["height"] = None
        items_list.append(entry)

    manifest["items"] = items_list
    manifest["included"] = sum(1 for i in plan.items if i.available)
    manifest["missing"] = sum(1 for i in plan.items if not i.available)
    manifest["producer"] = "FastPrompter"
    manifest["bundle_kind"] = plan.manifest.get("bundle_kind", "silo_bundle")
    manifest["scope"] = plan.manifest.get("scope", "full")
    manifest["source"] = plan.manifest.get("source", {
        "kind": plan.manifest.get("scope", "full"),
        "silo_title": plan.display_title,
        "category": plan.category,
        "line_start": 1,
        "line_end": max(1, len(plan.origin_text.splitlines())),
    })
    manifest["build"] = plan.manifest.get("build", get_build_provenance(plan.manifest.get("app_version", "")))
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["index_schema_version"] = INDEX_SCHEMA_VERSION
    manifest["bundle_status"] = plan.manifest.get("bundle_status", "complete")
    manifest["index_status"] = plan.manifest.get("index_status", "full")
    manifest["canonical_source"] = plan.manifest.get("canonical_source", plan.text_member)
    manifest["warnings"] = plan.manifest.get("warnings", [])
    manifest["omitted_local_refs"] = plan.manifest.get("omitted_local_refs", [])
    manifest["privacy"] = plan.manifest.get("privacy", {})
    manifest["capabilities"] = _bundle_capabilities(plan.index_data)
    valid_members = {i.member for i in plan.items if i.available and i.member.startswith("media/")}
    unscoped = set(plan.index_data.get("unscoped_media", [])) if plan.index_data else set()
    manifest["requirement_count"] = len(plan.index_data.get("requirements", [])) if plan.index_data else 0
    manifest["group_count"] = len(plan.index_data.get("groups", [])) if plan.index_data else 0
    manifest["scoped_media_count"] = len(valid_members - unscoped)
    manifest["unscoped_media_count"] = len(unscoped)

    # T-1417: one final privacy boundary over every user-derived string that
    # enters a generated member, applied field by field.
    manifest["silo_title"] = _share_safe(manifest.get("silo_title"))
    manifest["category"] = _share_safe(manifest.get("category"))
    source_meta = manifest.get("source")
    if isinstance(source_meta, dict):
        source_meta["silo_title"] = _share_safe(source_meta.get("silo_title"))
        source_meta["category"] = _share_safe(source_meta.get("category"))

    # No absolute source paths: a share bundle is not a filesystem listing.
    return manifest


def with_hashes(plan: BundlePlan, hashes: dict, fingerprint: str | None = None) -> BundlePlan:
    """Return a copy of ``plan`` whose manifest carries the stream digests."""
    manifest = dict(plan.manifest)
    items = []
    for entry in manifest.get("items", []):
        digest = hashes.get(entry["member"])
        items.append({**entry, "sha256": digest} if digest else dict(entry))
    manifest["items"] = items
    manifest["hashes"] = dict(hashes)
    if fingerprint:
        manifest["content_fingerprint"] = fingerprint
    return replace(plan, manifest=manifest)


# ---------------------------------------------------------------------------
# Content fingerprint & Fast cache (T-1411)
# ---------------------------------------------------------------------------

def file_stat_signature(path: str) -> tuple[int, int] | None:
    """(size, mtime_ns) or None if inaccessible."""
    try:
        st = os.stat(path)
        mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
        return (st.st_size, mtime_ns)
    except OSError:
        return None


def sha256_file(path: str, cancel=None) -> str:
    """Read and hash one file in background."""
    digest = hashlib.sha256(usedforsecurity=False)
    with open(path, "rb") as fh:
        while True:
            if cancel is not None and cancel.is_set():
                raise _Cancelled()
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def resolve_plan_hashes(plan: BundlePlan, source_cache: dict | None = None, cancel=None) -> tuple[dict, dict]:
    """Resolve SHA256 for all available items, using the fast cache when valid.

    Returns ``(member_hashes, updated_cache)`` where member_hashes maps
    ``member -> sha256`` and updated_cache maps ``source_path -> {size, mtime_ns, sha256}``.
    """
    member_hashes = {}
    updated_cache = dict(source_cache or {})
    for item in plan.items:
        if cancel is not None and cancel.is_set():
            raise _Cancelled()
        if not item.available:
            continue
        sig = file_stat_signature(item.source)
        cached = updated_cache.get(item.source) if sig else None
        h = None
        if isinstance(cached, dict) and sig:
            if cached.get("size") == sig[0] and cached.get("mtime_ns") == sig[1]:
                h = cached.get("sha256")
        if h:
            member_hashes[item.member] = h
        else:
            try:
                h = sha256_file(item.source, cancel)
                member_hashes[item.member] = h
                if sig:
                    updated_cache[item.source] = {
                        "size": sig[0],
                        "mtime_ns": sig[1],
                        "sha256": h,
                    }
            except OSError:
                pass

    # Hash generated text members
    if plan.text_member and plan.text_body is not None:
        member_hashes[plan.text_member] = hashlib.sha256(
            plan.text_body.encode("utf-8")).hexdigest()
    if plan.index_member and plan.index_data is not None:
        idx_bytes = json.dumps(plan.index_data, indent=2, ensure_ascii=False).encode("utf-8")
        member_hashes[plan.index_member] = hashlib.sha256(idx_bytes).hexdigest()
    if plan.readme_member and plan.readme_body is not None:
        member_hashes[plan.readme_member] = hashlib.sha256(
            plan.readme_body.encode("utf-8")).hexdigest()

    return member_hashes, updated_cache


def compute_content_fingerprint(plan: BundlePlan, hashes: dict) -> str:
    """A deterministic SHA256 over the logical portable bundle payload (T-1411/T-1413 § 29).

    Excludes volatile metadata such as created_at, archive output timestamps,
    and output paths.

    T-1417 § 23/24: the structured index is a DERIVED projection of the very
    Markdown and members already hashed here, and it is not knowable before
    publication -- so folding it in made the preflight identity (main.py reuse
    check) and the published identity describe two different logical payloads
    the moment any media went missing. The fingerprint is therefore a function
    of the portable payload alone, and items are sorted by member so that the
    planner's document order and the writer's included-then-missing order
    cannot produce two identities for one archive. FINGERPRINT_SCHEMA is bumped
    to 6 because the folded facts changed.
    """
    payload = {
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "bundle_kind": plan.manifest.get("bundle_kind", "silo_bundle"),
        "scope": plan.manifest.get("scope", "full"),
        "display_title": plan.display_title,
        "category": plan.category,
        "text_included": bool(plan.text_member),
        "text_member": plan.text_member,
        "text_sha256": hashes.get(plan.text_member) if plan.text_member else None,
        "media_only": bool(plan.manifest.get("media_only")),
        "portable_paths": bool(plan.manifest.get("portable_paths")),
        "attachments_included": bool(plan.manifest.get("attachments_included")),
        "items": [
            {
                "member": item.member,
                "media_type": item.media_type,
                "available": item.available,
                "sha256": hashes.get(item.member) if item.available else None,
                "silo_relative_path": item.silo_relative_path,
            }
            for item in sorted(plan.items, key=lambda i: i.member)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_reuse_candidate(
    zip_path: str,
    expected_fingerprint: str,
    expected_size: int | None = None,
    expected_mtime_ns: int | None = None,
) -> bool:
    """Check whether an existing archive matches the candidate (T-1411/T-1413 § 18)."""
    try:
        if not zip_path or not os.path.isfile(zip_path):
            return False
        st = os.stat(zip_path)
        actual_size = st.st_size
        actual_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

        if expected_size is not None and expected_size > 0:
            if actual_size != expected_size:
                return False

        with zipfile.ZipFile(zip_path, "r") as zf:
            if "manifest.json" not in zf.namelist():
                return False
            data = json.loads(zf.read("manifest.json").decode("utf-8"))
            if data.get("schema_version") not in REUSABLE_SCHEMAS:
                return False
            actual_fp = data.get("content_fingerprint")
            if not actual_fp or actual_fp != expected_fingerprint:
                return False

            # Check if stat matches recorded history exactly
            stat_matches = (
                expected_mtime_ns is not None
                and expected_mtime_ns > 0
                and actual_mtime_ns == expected_mtime_ns
                and (expected_size is None or actual_size == expected_size)
            )

            if stat_matches:
                return True

            # Suspicious / changed mtime / no mtime recorded: deep verification
            if zf.testzip() is not None:
                return False

            manifest_hashes = data.get("hashes", {})
            for member, exp_hash in manifest_hashes.items():
                if member not in zf.namelist():
                    return False
                member_bytes = zf.read(member)
                h = hashlib.sha256(member_bytes).hexdigest()
                if h != exp_hash:
                    return False

            return True
    except Exception:
        return False


def _is_proven_fastprompter_bundle(zip_path: str, expected_fingerprint: str | None = None) -> bool:
    """Positive ownership proof before retention deletion (T-1413 § 15)."""
    try:
        if not zip_path or not os.path.isfile(zip_path):
            return False
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "manifest.json" not in zf.namelist():
                return False
            data = json.loads(zf.read("manifest.json").decode("utf-8"))
            schema = data.get("schema_version")
            if schema not in (1, 2, 3, 4, 5, 6):
                return False
            if schema >= 4:
                if data.get("producer") != "FastPrompter" or data.get("bundle_kind") not in ("silo_bundle", "selection_bundle"):
                    return False
            actual_fp = data.get("content_fingerprint")
            if not actual_fp:
                return False
            if expected_fingerprint and actual_fp != expected_fingerprint:
                return False
            return True
    except Exception:
        return False


def prune_silo_history(records: list[dict], canonical_exports_dir: str,
                       keep_versions: int, prune_custom: bool = False,
                       bundle_kind: str | None = None) -> tuple[list[dict], list[str]]:
    """Apply retention to managed bundle history (T-1411/T-1413 §§ 14-16, T-1414).

    ``records`` is ordered newest-first. By default, auto-pruning affects only
    bundles located in ``canonical_exports_dir``. Excess managed archives are
    verified for positive FastPrompter ownership before deletion.
    """
    if keep_versions < 0:
        return records, []
    canon_dir = _canonical(canonical_exports_dir) if canonical_exports_dir else ""
    kept = []
    pruned_paths = []
    managed_count = 0

    for rec in records:
        path = rec.get("path")
        if not path:
            continue

        if bundle_kind is not None:
            rec_kind = rec.get("bundle_kind") or "silo_bundle"
            if rec_kind != bundle_kind:
                kept.append(rec)
                continue

        rec_dir = _canonical(os.path.dirname(path))
        is_canonical = bool(canon_dir and rec_dir == canon_dir)

        if not is_canonical and not prune_custom:
            kept.append(rec)
            continue

        managed_count += 1
        if managed_count <= keep_versions:
            kept.append(rec)
        else:
            # Excess version; delete ONLY if positively proven to be owned by FastPrompter
            if os.path.isfile(path):
                rec_fp = rec.get("content_fingerprint")
                if _is_proven_fastprompter_bundle(path, rec_fp):
                    try:
                        os.remove(path)
                        pruned_paths.append(path)
                    except OSError:
                        kept.append(rec)
                else:
                    # Uncertain / foreign / unproven: NEVER delete!
                    kept.append(rec)
            # Missing files are dropped from history without deletion

    return kept, pruned_paths


# ---------------------------------------------------------------------------
# Atomic publication
# ---------------------------------------------------------------------------

_CHUNK = 1 << 20


def allocate_bundle_path(target_dir: str, archive_name: str) -> str:
    """A destination that does not exist yet. Never clobbers (section 7)."""
    base, ext = os.path.splitext(archive_name)
    candidate = os.path.join(target_dir, archive_name)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(target_dir, f"{base}_{n}{ext}")
        n += 1
        if n > 9999:
            raise OSError("could not allocate a unique bundle filename")
    return candidate


def _sha256_stream(zf, item: BundleItem, cancel=None):
    """Copy one file into the archive, hashing the same bytes on the way in."""
    digest = hashlib.sha256(usedforsecurity=False)
    written = 0
    with open(item.source, "rb") as src, zf.open(item.member, "w") as dst:
        while True:
            if cancel is not None and cancel.is_set():
                raise _Cancelled()
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            dst.write(chunk)
            written += len(chunk)
    return digest.hexdigest(), written


class _Cancelled(Exception):
    pass


def write_bundle(plan: BundlePlan, progress=None, cancel=None) -> BundleResult:
    """Build into a unique temp sibling, publish atomically, never clobber.

    Streams media first, finalizes portable Markdown, structured index,
    README and manifest from actual publication facts (T-1413 § 7).
    """
    hashes = {}
    included = []
    missing = []
    total = len(plan.items) + (1 if plan.text_member else 0) + 1
    done = 0
    tmp = None
    try:
        os.makedirs(plan.target_dir, exist_ok=True)
        target = allocate_bundle_path(plan.target_dir, plan.archive_name)
        tmp = path_safety.unique_temp_path(target, "fpbundle")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Stream media items first to determine factual inclusion
            for item in plan.items:
                if cancel is not None and cancel.is_set():
                    raise _Cancelled()
                if not item.available:
                    missing.append(item)
                    done += 1
                    if progress:
                        progress(done, total, item.member)
                    continue
                try:
                    digest, _size = _sha256_stream(zf, item, cancel)
                except OSError:
                    # The source vanished between planning and packing.
                    missing.append(replace(item, available=False))
                    done += 1
                    if progress:
                        progress(done, total, item.member)
                    continue
                hashes[item.member] = digest
                included.append(item)
                done += 1
                if progress:
                    progress(done, total, item.member)

            # 2. Build final portable Markdown from the ACTUAL included map.
            # T-1417: a source that vanished between planning and packing has no
            # member in this ZIP, so it must not become a media/... link to a
            # file that is not there. portable_markdown turns it into the
            # existing honest omission marker instead.
            hide_paths = bool(plan.manifest.get("portable_paths", True))
            included_bundle_map = {item.source: item.member for item in included}
            refs = find_local_refs(plan.origin_text, None)
            final_text_body = None
            omitted_local_refs: list[dict] = []
            privacy_stats: dict = {
                "local_refs_rewritten": 0,
                "local_refs_omitted": 0,
                "residual_paths_redacted": 0,
            }
            if plan.text_member:
                if cancel is not None and cancel.is_set():
                    raise _Cancelled()
                final_text_body = portable_markdown(
                    plan.origin_text,
                    refs,
                    included_bundle_map,
                    hide_paths,
                    omitted_refs_out=omitted_local_refs,
                    privacy_stats_out=privacy_stats,
                )
                text_bytes = (final_text_body or "").encode("utf-8")
                hashes[plan.text_member] = hashlib.sha256(text_bytes).hexdigest()
                zf.writestr(plan.text_member, text_bytes)
                done += 1
                if progress:
                    progress(done, total, plan.text_member)

            # 3. Build and validate final structured index (bounded fail-open degradation)
            included_members = {item.member for item in included}
            missing_members = {item.member for item in missing}

            final_index_data = None
            index_status = "full"
            manifest_warnings: list[dict] = []

            for mm in sorted(missing_members):
                manifest_warnings.append({"code": "MEDIA_SOURCE_MISSING", "member": mm})

            for om in omitted_local_refs:
                manifest_warnings.append({
                    "code": "LOCAL_REFERENCE_OMITTED",
                    "display_name": om.get("display_name"),
                    "kind": om.get("kind"),
                })

            if privacy_stats.get("residual_paths_redacted", 0) > 0:
                manifest_warnings.append({
                    "code": "RESIDUAL_LOCAL_PATH_REDACTED",
                    "count": privacy_stats["residual_paths_redacted"],
                })

            if plan.index_member:
                # Attempt 1: Full structured index from final_text_body
                try:
                    silo_idx = silo_index.build_silo_index(
                        markdown_text=final_text_body,
                        source_member=plan.text_member,
                        items=included,
                        missing_items=missing,
                    )
                    cand_index = silo_idx.to_dict()
                    valid, _reason = silo_index.validate_index_structure(
                        cand_index,
                        included_members,
                        hide_local_paths=hide_paths,
                        plan_missing_members=missing_members,
                    )
                    if valid:
                        final_index_data = cand_index
                        index_status = "full"
                    else:
                        manifest_warnings.append({"code": "INDEX_VALIDATION_FAILED", "phase": "full"})
                except Exception:
                    # T-1417 § 14/15: str(exc) may carry an absolute path, a
                    # username or a temp directory. The share archive keeps the
                    # portable fact only; the raw exception stays in the local
                    # application log.
                    logger.exception("silo bundle: full structured index build failed")
                    manifest_warnings.append({"code": "INDEX_PARSE_ERROR", "phase": "full"})

                # Attempt 2: Bounded fallback index if full index failed
                if final_index_data is None:
                    try:
                        fallback_idx = silo_index.build_fallback_index(
                            markdown_text=final_text_body,
                            source_member=plan.text_member,
                            items=included,
                            missing_items=missing,
                            reasons=[w["code"] for w in manifest_warnings],
                        )
                        cand_fb = fallback_idx.to_dict()
                        valid, _reason = silo_index.validate_index_structure(
                            cand_fb,
                            included_members,
                            hide_local_paths=hide_paths,
                            plan_missing_members=missing_members,
                        )
                        if valid:
                            final_index_data = cand_fb
                            index_status = "degraded"
                            manifest_warnings.append({
                                "code": "INDEX_FALLBACK_USED",
                                "detail": "Structured index degraded to fallback representation",
                            })
                        else:
                            manifest_warnings.append({"code": "FALLBACK_INDEX_VALIDATION_FAILED", "phase": "fallback"})
                    except Exception:
                        # Same rule as the full tier: portable fact to the archive,
                        # raw exception to the local log only.
                        logger.exception("silo bundle: fallback index build failed")
                        manifest_warnings.append({"code": "FALLBACK_INDEX_ERROR", "phase": "fallback"})

                # Attempt 3: If even fallback failed, omit index safely
                if final_index_data is None:
                    index_status = "unavailable"
                    manifest_warnings.append({
                        "code": "INDEX_UNAVAILABLE",
                        "detail": "Structured index omitted due to secondary generation failure",
                    })

                # Write index to ZIP only if valid index data exists
                if final_index_data is not None:
                    if cancel is not None and cancel.is_set():
                        raise _Cancelled()
                    idx_bytes = json.dumps(
                        final_index_data, indent=2, ensure_ascii=False
                    ).encode("utf-8")
                    hashes[plan.index_member] = hashlib.sha256(idx_bytes).hexdigest()
                    zf.writestr(plan.index_member, idx_bytes)

            # 4. Final README sidecar
            if plan.readme_member:
                if cancel is not None and cancel.is_set():
                    raise _Cancelled()
                now_iso = plan.manifest.get("created_at") or _dt.datetime.now().isoformat(timespec="seconds")
                req_count = len(final_index_data.get("requirements", [])) if final_index_data else 0
                grp_count = len(final_index_data.get("groups", [])) if final_index_data else 0
                readme_body = _build_readme(
                    title=plan.display_title,
                    category=plan.category,
                    created_iso=now_iso,
                    text_member=plan.text_member,
                    index_member=plan.index_member or "silo.index.json",
                    req_count=req_count,
                    group_count=grp_count,
                    media_count=len(included),
                    missing_count=len(missing),
                    bundle_kind=plan.manifest.get("bundle_kind", "silo_bundle"),
                    index_status=index_status,
                )
                readme_bytes = readme_body.encode("utf-8")
                hashes[plan.readme_member] = hashlib.sha256(readme_bytes).hexdigest()
                zf.writestr(plan.readme_member, readme_bytes)

            # 5. Build final manifest and content fingerprint
            updated_plan = replace(
                plan,
                items=tuple(included + missing),
                text_body=final_text_body,
                index_data=final_index_data,
            )
            manifest = _build_manifest(updated_plan)
            for entry in manifest.get("items", []):
                digest = hashes.get(entry["member"])
                if digest:
                    entry["sha256"] = digest
            manifest["hashes"] = dict(hashes)

            # Health classification
            if missing:
                bundle_status = "partial" if index_status == "full" else "degraded"
            elif index_status in ("degraded", "unavailable"):
                bundle_status = "degraded"
            else:
                bundle_status = "complete"

            manifest["bundle_status"] = bundle_status
            manifest["index_status"] = index_status
            manifest["canonical_source"] = plan.text_member
            manifest["warnings"] = manifest_warnings
            manifest["omitted_local_refs"] = omitted_local_refs
            manifest["privacy"] = privacy_stats
            manifest["capabilities"] = _bundle_capabilities(final_index_data)

            fp = compute_content_fingerprint(updated_plan, hashes)
            manifest["content_fingerprint"] = fp

            if cancel is not None and cancel.is_set():
                raise _Cancelled()
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )
            done += 1
            if progress:
                progress(done, total, "manifest.json")

        # Atomic publication
        os.rename(tmp, target)
        try:
            st = os.stat(target)
            archive_size = st.st_size
            archive_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
        except OSError:
            archive_size = 0
            archive_mtime_ns = 0

        signatures = {}
        for item in included:
            sig = file_stat_signature(item.source)
            if sig:
                signatures[item.source] = {
                    "size": sig[0],
                    "mtime_ns": sig[1],
                    "sha256": hashes.get(item.member),
                }

    except _Cancelled:
        if tmp:
            _discard(tmp)
        return BundleResult(None, tuple(included), tuple(missing), cancelled=True)
    except OSError as exc:
        if tmp:
            _discard(tmp)
        return BundleResult(None, tuple(included), tuple(missing),
                            error=str(exc) or exc.__class__.__name__)
    return BundleResult(
        target,
        tuple(included),
        tuple(missing),
        fingerprint=fp,
        hashes=hashes,
        signatures=signatures,
        archive_size=archive_size,
        archive_mtime_ns=archive_mtime_ns,
        bundle_status=bundle_status,
        index_status=index_status,
        warnings=tuple(w.get("code", str(w)) for w in manifest_warnings),
    )


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass

