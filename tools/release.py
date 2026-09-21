"""Publish the GitHub release for the current version — exact-commit, draft-first.

Usage:
    python tools/release.py [notes.md]

Preconditions (all refused with a message, never warned past):

- version parity across VERSION / pyproject.toml / FastPrompter.pyw / uv.lock;
- HEAD == origin/main after an explicit fetch (public releases come from main);
- local tag (when present) and REMOTE tag (when present) both point at HEAD;
- working tree clean (full porcelain, untracked included);
- a valid release receipt binding VERSION, HEAD, the EXE SHA256 and the EXE
  ProductVersion (tools/release_provenance.py writes it after build + probe).

Publication is draft-first: the release is created as a draft at the exact
HEAD SHA, assets (FastPrompter.exe + FastPrompter.exe.sha256) are uploaded and
verified remotely, and only then is the draft published. A published release is
immutable: re-running for an already-published tag aborts; a changed binary
requires a new VERSION. An existing DRAFT may be completed.

Run tools/build.py, tools/probe_release.py and tools/release_provenance.py
first, or use release.cmd which runs the full preflight.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_provenance as rp

REPO = "vacterro/FastPrompter"
ASSET = "FastPrompter.exe"
ASSET_SHA = ASSET + ".sha256"


def read_version() -> str:
    return rp.read_version()


def check_version_parity(version: str) -> None:
    rp.check_version_parity(version)


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


def fetch_origin() -> None:
    rp.git("fetch", "--tags", "origin")
    rp.git("fetch", "origin", "main")


def check_release_branch() -> None:
    head = rp.git_head()
    origin_main = rp.git("rev-parse", "origin/main")
    if head != origin_main:
        raise SystemExit(
            f"release HEAD {head[:12]} != origin/main {origin_main[:12]}; "
            "public releases are cut from main after the release commit lands"
        )


def check_clean_tree() -> None:
    if not rp.git_is_clean():
        raise SystemExit(
            "working tree is dirty (git status --porcelain is not empty); "
            "reconcile and commit before releasing"
        )


def check_tag_provenance(version: str) -> None:
    """Local AND remote tags, when present, must point at HEAD."""
    head = rp.git_head()
    tag = f"v{version}"
    local = rp.git("rev-parse", f"{tag}^{{commit}}", check=False)
    if local and local != head:
        raise SystemExit(
            "version already tagged at different commit; bump VERSION and run "
            "python tools/sync_release_version.py"
        )
    remote = rp.git_remote_tag_commit(tag)
    if remote is not None and remote != head:
        raise SystemExit(
            f"remote tag {tag} already points at {remote[:12]}, not HEAD {head[:12]}; "
            "do not overwrite history — bump VERSION for a changed release"
        )


def check_receipt(version: str, exe: str) -> None:
    receipt_path = rp.RECEIPT_PATH
    if not receipt_path.is_file():
        raise SystemExit(
            f"release receipt missing: {receipt_path} — run tools/release_provenance.py "
            "receipt after a clean-clone build and packaged probe"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"release receipt unreadable: {exc}")
    failures = rp.validate_receipt(receipt, rp.Path(exe), version, rp.git_head())
    if failures:
        raise SystemExit("release receipt does not bind this release: " + "; ".join(failures))


def read_notes(version: str) -> str:
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return open(sys.argv[1], encoding="utf-8").read()
    tag = f"v{version}"
    return (
        f"FastPrompter {tag} — portable single-file EXE for Windows.\n\n"
        "Download `FastPrompter.exe`, run it, press `Alt+X`. "
        "No install, no Python, no admin rights; your data lives in a "
        "`data/` folder next to the EXE.\n\n"
        "See the commit history for what changed."
    )


def ensure_draft(tok, tag: str, head: str, notes: str):
    rel = api(f"/repos/{REPO}/releases/tags/{tag}", tok)
    if rel is not None and not rel.get("draft"):
        raise SystemExit(
            f"release {tag} is already published and immutable; "
            "a changed binary requires a new VERSION"
        )
    if rel is None:
        rel = api(
            f"/repos/{REPO}/releases",
            tok,
            data=json.dumps(
                {
                    "tag_name": tag,
                    "target_commitish": head,
                    "name": f"FastPrompter {tag}",
                    "body": notes,
                    "draft": True,
                }
            ).encode(),
        )
        if not rel or "id" not in rel:
            raise SystemExit(f"Failed to create draft release: {rel}")
        print(f"Created draft release {tag} at {head[:12]}")
    else:
        api(
            f"/repos/{REPO}/releases/{rel['id']}",
            tok,
            data=json.dumps({"body": notes}).encode(),
            method="PATCH",
        )
        print(f"Completing existing draft release {rel.get('html_url', tag)}")
    return rel


def upload_asset(tok, rel, name: str, blob: bytes, ctype: str):
    for asset in rel.get("assets", []):
        if asset["name"] == name:
            api(f"/repos/{REPO}/releases/assets/{asset['id']}", tok, method="DELETE")
            print(f"Removed previous {name} from the draft")
    up = api(
        f"/repos/{REPO}/releases/{rel['id']}/assets?name={name}",
        tok,
        data=blob,
        ctype=ctype,
        host="uploads.github.com",
    )
    if not up:
        raise SystemExit(f"Failed to upload {name}")
    return up


def verify_draft(tok, tag: str, head: str, exe_hash: str, exe_size: int):
    fresh = api(f"/repos/{REPO}/releases/tags/{tag}", tok)
    if fresh is None:
        raise SystemExit("draft release vanished during verification")
    target = (fresh.get("target_commitish") or "").strip()
    if target != head:
        raise SystemExit(f"draft target_commitish {target!r} != release commit {head!r}")
    if fresh.get("name") != f"FastPrompter {tag}":
        raise SystemExit(f"draft name {fresh.get('name')!r} mismatch")
    assets = {asset["name"]: asset for asset in fresh.get("assets", [])}
    if ASSET not in assets:
        raise SystemExit(f"draft is missing asset {ASSET}")
    asset = assets[ASSET]
    if asset.get("size") != exe_size:
        raise SystemExit(f"uploaded {ASSET} size {asset.get('size')} != local {exe_size}")
    digest = asset.get("digest") or ""
    if digest and digest != f"sha256:{exe_hash}":
        raise SystemExit(f"uploaded {ASSET} digest {digest} != local sha256:{exe_hash}")
    if ASSET_SHA not in assets:
        raise SystemExit(f"draft is missing asset {ASSET_SHA}")
    print(f"Draft verified remotely: commit {head[:12]}, {ASSET} {exe_size} bytes")


def publish(tok, rel):
    return api(
        f"/repos/{REPO}/releases/{rel['id']}",
        tok,
        data=json.dumps({"draft": False}).encode(),
        method="PATCH",
    )


def verify_published_tag(tok, tag: str, head: str) -> None:
    ref = api(f"/repos/{REPO}/git/ref/tags/{tag}", tok)
    if ref is None:
        raise SystemExit(f"tag {tag} not found on GitHub after publish")
    obj = ref.get("object", {})
    sha = obj.get("sha", "")
    if obj.get("type") == "tag":
        tag_obj = api(f"/repos/{REPO}/git/tags/{sha}", tok)
        sha = (tag_obj or {}).get("object", {}).get("sha", "")
    if sha != head:
        raise SystemExit(f"remote tag {tag} -> {sha[:12]} != release commit {head[:12]}")
    print(f"Remote tag {tag} verified at {head[:12]}")


def main() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)
    version = read_version()
    check_version_parity(version)
    fetch_origin()
    check_release_branch()
    check_tag_provenance(version)
    check_clean_tree()
    exe = os.path.join("build", ASSET)
    if not os.path.exists(exe):
        raise SystemExit("build/FastPrompter.exe missing — run tools/build.py first")
    check_receipt(version, exe)

    tag = f"v{version}"
    head = rp.git_head()
    notes = read_notes(version)
    blob = open(exe, "rb").read()
    exe_hash = rp.sha256_file(rp.Path(exe))
    sha_blob = f"{exe_hash}  {ASSET}\n".encode()

    tok = get_token()
    rel = ensure_draft(tok, tag, head, notes)
    uploaded = upload_asset(tok, rel, ASSET, blob, "application/octet-stream")
    upload_asset(tok, rel, ASSET_SHA, sha_blob, "text/plain")
    verify_draft(tok, tag, head, exe_hash, len(blob))
    published = publish(tok, rel)
    verify_published_tag(tok, tag, head)
    print(f"Published {published.get('html_url', tag)}")
    print(f"Download: {uploaded.get('browser_download_url', '')}")


if __name__ == "__main__":
    main()
