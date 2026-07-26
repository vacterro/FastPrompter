"""Snapshot .saipen/ state so a wipe is recoverable (SYS-02).

`.saipen/` is gitignored, so on 24.07 a stray saitranslate INIT overwrote
BOARD.md, LOG.md and STATE.md with a blank template and there was no git
history to fall back on: 175KB of LOG and a ~90-ticket board were gone, and
only a 3-day-old copy in `.saipen/recovery/` survived.

This keeps timestamped copies of the three core files under
`.saipen/snapshots/`, skipping the write when nothing changed (so running it
often is cheap) and pruning old generations.

Deliberately additive: it never touches .gitignore and never deletes
anything outside its own `snapshots/` directory. Tracking `.saipen/` in git
is the other half of SYS-02 and stays the user's call.

Usage:
    python tools/saipen_snapshot.py            # snapshot if changed
    python tools/saipen_snapshot.py --force    # snapshot regardless
    python tools/saipen_snapshot.py --list     # show generations
    python tools/saipen_snapshot.py --keep 40  # prune to N generations
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CORE_FILES = ("STATE.md", "BOARD.md", "LOG.md")
DEFAULT_KEEP = 30


def saipen_root(start: Path | None = None) -> Path:
    """Walk up for a directory containing .saipen/, like the wiki sync does.

    A fixed parent-hop count breaks the moment the script is moved; this
    keeps working from anywhere inside the project.
    """
    here = (start or Path(__file__).resolve()).parent
    for cand in (here, *here.parents):
        if (cand / ".saipen").is_dir():
            return cand / ".saipen"
    raise SystemExit("no .saipen/ found above " + str(here))


def _digest(root: Path) -> str:
    """One hash over all three files, so an unchanged trio is a no-op."""
    h = hashlib.sha256()
    for name in CORE_FILES:
        p = root / name
        h.update(name.encode())
        h.update(b"\0")
        h.update(p.read_bytes() if p.is_file() else b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def _generations(snap_dir: Path) -> list[Path]:
    if not snap_dir.is_dir():
        return []
    return sorted((d for d in snap_dir.iterdir() if d.is_dir()), key=lambda d: d.name)


def snapshot(root: Path, force: bool = False, keep: int = DEFAULT_KEEP) -> Path | None:
    snap_dir = root / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    digest = _digest(root)

    gens = _generations(snap_dir)
    if not force and gens:
        stamp = gens[-1] / ".digest"
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == digest:
            return None                      # nothing changed since last time

    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = snap_dir / name
    if dest.exists():                        # same second, still keep both
        dest = snap_dir / (name + "-b")
    dest.mkdir()
    copied = 0
    for fname in CORE_FILES:
        src = root / fname
        if src.is_file():
            shutil.copy2(src, dest / fname)
            copied += 1
    if copied == 0:
        dest.rmdir()                         # nothing to preserve
        return None
    (dest / ".digest").write_text(digest, encoding="utf-8")

    # prune oldest generations, newest kept
    for old in _generations(snap_dir)[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="snapshot even if unchanged")
    ap.add_argument("--list", action="store_true", help="list existing generations")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                    help=f"generations to retain (default {DEFAULT_KEEP}, 0 = keep all)")
    args = ap.parse_args(argv)

    root = saipen_root()
    snap_dir = root / "snapshots"

    if args.list:
        gens = _generations(snap_dir)
        if not gens:
            print("no snapshots yet")
            return 0
        for d in gens:
            sizes = ", ".join(
                f"{f.name} {f.stat().st_size}B"
                for f in sorted(d.iterdir()) if f.name in CORE_FILES
            )
            print(f"{d.name}  {sizes}")
        print(f"\n{len(gens)} generation(s) in {snap_dir}")
        return 0

    made = snapshot(root, force=args.force, keep=args.keep)
    if made is None:
        # ASCII only: a Windows console at cp1251 renders an em dash as a
        # replacement char, which makes the tool look broken
        print("unchanged since the last snapshot - nothing written")
    else:
        print(f"snapshot: {made}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
