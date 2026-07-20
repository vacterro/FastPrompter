"""Create or update the GitHub release for the current version.

Usage:
    python tools/release.py [notes.md]

Reads the version from pyproject.toml, creates (or updates) the release
tagged v<version> on GitHub, and uploads build/FastPrompter.exe as the
downloadable asset (replacing any previous one). Uses the GitHub token
stored by git's credential helper — the same one `git push` uses.

Run tools/build.py first, or use release.cmd which does both.
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "vacterro/FastPrompter"
ASSET = "FastPrompter.exe"


def get_token() -> str:
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n",
        capture_output=True,
        text=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("No GitHub credential found (git credential fill)")


def api(path, tok, data=None, method=None, ctype="application/json", host="api.github.com"):
    req = urllib.request.Request(
        f"https://{host}{path}", data=data, method=method or ("POST" if data else "GET")
    )
    req.add_header("Authorization", f"Bearer {tok}")
    req.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SystemExit(f"GitHub API {e.code} on {path}: {e.read().decode()[:300]}")


def read_version() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    text = open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("version not found in pyproject.toml")
    return m.group(1)


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)
    exe = os.path.join("build", ASSET)
    if not os.path.exists(exe):
        raise SystemExit("build/FastPrompter.exe missing — run tools/build.py first")

    version = read_version()
    tag = f"v{version}"
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        notes = open(sys.argv[1], encoding="utf-8").read()
    else:
        notes = (
            f"FastPrompter {tag} — portable single-file EXE for Windows.\n\n"
            "Download `FastPrompter.exe`, run it, press `Alt+X`. "
            "No install, no Python, no admin rights; your data lives in a "
            "`data/` folder next to the EXE.\n\n"
            "See the commit history for what changed."
        )

    tok = get_token()
    rel = api(f"/repos/{REPO}/releases/tags/{tag}", tok)
    if rel is None:
        rel = api(
            f"/repos/{REPO}/releases",
            tok,
            data=json.dumps(
                {
                    "tag_name": tag,
                    "target_commitish": "main",
                    "name": f"FastPrompter {tag}",
                    "body": notes,
                }
            ).encode(),
        )
        if not rel or 'id' not in rel:
            raise SystemExit(f"Failed to create release: {rel}")
        print(f"Created release {rel.get('html_url', '')}")
    else:
        api(
            f"/repos/{REPO}/releases/{rel['id']}",
            tok,
            data=json.dumps({"body": notes}).encode(),
            method="PATCH",
        )
        print(f"Updated release {rel['html_url']}")

    for asset in rel.get("assets", []):
        if asset["name"] == ASSET:
            api(f"/repos/{REPO}/releases/assets/{asset['id']}", tok, method="DELETE")
            print("Removed previous asset")

    with open(exe, "rb") as f:
        blob = f.read()
    up = api(
        f"/repos/{REPO}/releases/{rel['id']}/assets?name={ASSET}",
        tok,
        data=blob,
        ctype="application/octet-stream",
        host="uploads.github.com",
    )
    print(f"Uploaded {ASSET} ({len(blob) / 1048576:.1f} MB)")
    print(f"Download: {up['browser_download_url']}")


if __name__ == "__main__":
    main()
