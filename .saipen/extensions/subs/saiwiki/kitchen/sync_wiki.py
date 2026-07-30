#!/usr/bin/env python3
"""
GitHub Wiki Sync Helper Script for FastPrompter.
Clones/pulls https://github.com/vacterro/FastPrompter.wiki.git and synchronizes
all wiki pages from subs/saiwiki/wiki/.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_URL = "https://github.com/vacterro/FastPrompter.wiki.git"
SCRIPT_DIR = Path(__file__).resolve().parent


def _find_project_root(start: Path) -> Path:
    """Walk up from start to the .saipen/ ancestor and return its parent.

    Avoids hardcoding a fixed number of parent-hops, which breaks silently
    if this subSaipen ever gets nested deeper (e.g. .saipen/saiwiki/ moving
    to .saipen/extensions/subs/saiwiki/, as happened once already).
    """
    for candidate in (start, *start.parents):
        if candidate.name == ".saipen":
            return candidate.parent
    raise RuntimeError(f"no .saipen/ ancestor found above {start}")


PROJECT_ROOT = _find_project_root(SCRIPT_DIR)
DEFAULT_WIKI_DIR = PROJECT_ROOT / "docs" / "wiki"
WORK_REPO_DIR = SCRIPT_DIR / ".wiki_repo"


def run_cmd(cmd, cwd=None):
    """Executes a shell command and raises on error."""
    print(f"[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        print(f"[ERROR] Command failed with code {res.returncode}:\n{res.stderr}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return res.stdout.strip()


def sync_wiki(repo_url, source_dir, push=False, dry_run=False):
    """Synchronizes markdown wiki files into target git repository."""
    source_path = Path(source_dir).resolve()
    if not source_path.exists() or not source_path.is_dir():
        print(f"[ERROR] Source wiki directory does not exist: {source_path}", file=sys.stderr)
        sys.exit(1)

    print("=== FastPrompter Wiki Sync ===")
    print(f"Source Directory: {source_path}")
    print(f"Target Repo URL:  {repo_url}")
    print(f"Push Mode:        {'ENABLED' if push else 'DISABLED (Use --push to push changes)'}")
    print(f"Dry Run:          {dry_run}")
    print("-------------------------------")

    # Step 1: Clone or Pull Target Repository
    if WORK_REPO_DIR.exists() and (WORK_REPO_DIR / ".git").exists():
        print(f"Updating existing working repo at {WORK_REPO_DIR}...")
        try:
            run_cmd(["git", "pull", "--rebase"], cwd=WORK_REPO_DIR)
        except Exception as e:
            print(f"[WARN] Failed to pull existing repo: {e}. Re-cloning...")
            shutil.rmtree(WORK_REPO_DIR, ignore_errors=True)

    if not WORK_REPO_DIR.exists():
        print(f"Cloning {repo_url} into {WORK_REPO_DIR}...")
        run_cmd(["git", "clone", repo_url, str(WORK_REPO_DIR)])

    # Step 2: Copy Files from source_dir into WORK_REPO_DIR
    copied_files = []
    for file_path in source_path.glob("*.md"):
        target_file = WORK_REPO_DIR / file_path.name
        print(f"Copying {file_path.name} -> {target_file}")
        if not dry_run:
            shutil.copy2(file_path, target_file)
        copied_files.append(file_path.name)

    print(f"\nSuccessfully staged {len(copied_files)} wiki pages.")

    if dry_run:
        print("[DRY-RUN] Completed without modifying target git repository.")
        return

    # Step 3: Git Status and Commit
    status = run_cmd(["git", "status", "--porcelain"], cwd=WORK_REPO_DIR)
    if not status:
        print("[INFO] No changes detected in wiki repository. Wiki is up to date!")
        return

    print("\nGit changes detected:")
    print(status)

    run_cmd(["git", "add", "-A"], cwd=WORK_REPO_DIR)
    commit_msg = "docs(wiki): sync FastPrompter technical wiki pages from saiwiki"
    run_cmd(["git", "commit", "-m", commit_msg], cwd=WORK_REPO_DIR)
    print(f"[SUCCESS] Committed changes: '{commit_msg}'")

    # Step 4: Push to Remote
    if push:
        print(f"Pushing updates to {repo_url}...")
        run_cmd(["git", "push", "origin", "HEAD"], cwd=WORK_REPO_DIR)
        print("[SUCCESS] GitHub Wiki successfully pushed!")
    else:
        print("[NOTE] Changes committed locally in .wiki_repo. Run with --push to push to GitHub.")


def main():
    parser = argparse.ArgumentParser(description="Synchronize FastPrompter Wiki pages to GitHub Wiki repository.")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="Target GitHub Wiki Git URL")
    parser.add_argument("--wiki-dir", default=str(DEFAULT_WIKI_DIR), help="Source directory containing .md wiki pages")
    parser.add_argument("--push", action="store_true", help="Automatically push committed changes to GitHub")
    parser.add_argument("--dry-run", action="store_true", help="Simulate synchronization without altering files")

    args = parser.parse_args()
    try:
        sync_wiki(args.repo_url, args.wiki_dir, push=args.push, dry_run=args.dry_run)
    except Exception as err:
        print(f"\n[FATAL ERROR] {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
