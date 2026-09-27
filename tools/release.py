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

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_provenance as rp

REPO = "vacterro/FastPrompter"
ASSET = "FastPrompter.exe"
ASSET_SHA = ASSET + ".sha256"


class _StripAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward the GitHub API token to the signed asset-download host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(
            newurl
        ).netloc:
            redirected.remove_header("Authorization")
            redirected.unredirected_hdrs.pop("Authorization", None)
        return redirected


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
        with urllib.request.urlopen(req) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise SystemExit(f"GitHub API {exc.code} on {path}: {exc.read().decode()[:300]}")


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


def find_release(tok, tag: str):
    """Find published or draft releases; GitHub's by-tag endpoint excludes drafts."""
    page = 1
    while True:
        releases = api(f"/repos/{REPO}/releases?per_page=100&page={page}", tok)
        if releases is None:
            return None
        if isinstance(releases, dict):
            # Compatibility for clients/tests that return a direct by-tag object.
            return releases
        if not isinstance(releases, list):
            raise SystemExit("GitHub releases collection response was not a list")
        for release in releases:
            if release.get("tag_name") == tag:
                return release
        if len(releases) < 100:
            return None
        page += 1


def verify_draft_target(release, tag: str, head: str):
    if release is None:
        raise SystemExit("draft release vanished during verification")
    if not release.get("draft"):
        raise SystemExit("release stopped being a draft before publication")
    if release.get("tag_name") != tag:
        raise SystemExit(f"draft tag {release.get('tag_name')!r} != {tag!r}")
    target = (release.get("target_commitish") or "").strip()
    if target != head:
        raise SystemExit(f"draft target_commitish {target!r} != release commit {head!r}")
    if release.get("name") != f"FastPrompter {tag}":
        raise SystemExit(f"draft name {release.get('name')!r} mismatch")
    return release


def ensure_draft(tok, tag: str, head: str, notes: str):
    release = find_release(tok, tag)
    if release is not None and not release.get("draft"):
        raise SystemExit(
            f"release {tag} is already published and immutable; "
            "a changed binary requires a new VERSION"
        )
    if release is not None:
        if not release.get("draft"):
            raise SystemExit(
                f"release {tag} is already published and immutable; "
                "a changed binary requires a new VERSION"
            )
        verify_draft_target(release, tag, head)
        response = api(
            f"/repos/{REPO}/releases/{release['id']}",
            tok,
            # tag_name/target_commitish must ride along: a body-only PATCH makes
            # GitHub reset an untagged draft to its "untagged-<id>" placeholder.
            data=json.dumps(
                {"body": notes, "tag_name": tag, "target_commitish": head}
            ).encode(),
            method="PATCH",
        )
        print(f"Completing existing draft release {release.get('html_url', tag)}")
        return response or release

    release = api(
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
    if not release or "id" not in release:
        raise SystemExit(f"Failed to create draft release: {release}")
    verify_draft_target(release, tag, head)
    print(f"Created draft release {tag} at {head[:12]}")
    return release


def api_asset_bytes(tok, asset: dict, limit: int | None = None) -> bytes:
    """Read an uploaded asset through GitHub's authenticated API endpoint."""
    asset_id = asset.get("id")
    if not asset_id:
        raise SystemExit(f"release asset {asset.get('name')!r} has no API id")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}"
    )
    req.add_header("Authorization", f"Bearer {tok}")
    req.add_header("Accept", "application/octet-stream")
    opener = urllib.request.build_opener(_StripAuthRedirectHandler())
    try:
        with opener.open(req) as response:
            body = response.read() if limit is None else response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"could not read release asset {asset.get('name')!r} ({exc.code})")
    if limit is not None and len(body) > limit:
        raise SystemExit(f"release asset {asset.get('name')!r} exceeds {limit} bytes")
    return body


def asset_sha256(tok, asset: dict) -> str:
    return hashlib.sha256(api_asset_bytes(tok, asset)).hexdigest()


def checksum_blob(exe_hash: str) -> bytes:
    return f"{exe_hash}  {ASSET}\n".encode("ascii")


def check_checksum_text(body: bytes, exe_hash: str) -> None:
    expected = checksum_blob(exe_hash)
    if body != expected:
        raise SystemExit(f"checksum asset content mismatch: {body[:160]!r}")


def upload_asset(tok, release: dict, name: str, blob: bytes, ctype: str):
    expected_hash = hashlib.sha256(blob).hexdigest()
    for asset in release.get("assets", []):
        if asset.get("name") != name:
            continue
        digest = (asset.get("digest") or "").removeprefix("sha256:")
        if asset.get("size") == len(blob) and digest == expected_hash:
            print(f"Reusing verified draft asset {name}")
            return asset
        if asset_sha256(tok, asset) == expected_hash:
            print(f"Reusing verified draft asset {name}")
            return asset
        api(f"/repos/{REPO}/releases/assets/{asset['id']}", tok, method="DELETE")
        print(f"Removed mismatched {name} from the draft")
    upload = api(
        f"/repos/{REPO}/releases/{release['id']}/assets?name={name}",
        tok,
        data=blob,
        ctype=ctype,
        host="uploads.github.com",
    )
    if not upload:
        raise SystemExit(f"Failed to upload {name}")
    return upload


def fetch_draft(tok, tag: str, head: str, release_id: int):
    """Fetch a draft by ID; /releases/tags/{tag} intentionally omits drafts."""
    release = api(f"/repos/{REPO}/releases/{release_id}", tok)
    return verify_draft_target(release, tag, head)


def verify_draft(tok, tag: str, head: str, exe_hash: str, exe_size: int, release_id: int):
    release = fetch_draft(tok, tag, head, release_id)
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    exe_asset = assets.get(ASSET)
    checksum_asset = assets.get(ASSET_SHA)
    if exe_asset is None or checksum_asset is None:
        raise SystemExit(f"draft must contain {ASSET} and {ASSET_SHA}")
    if exe_asset.get("size") != exe_size:
        raise SystemExit(f"uploaded {ASSET} size {exe_asset.get('size')} != local {exe_size}")
    digest = (exe_asset.get("digest") or "").removeprefix("sha256:")
    if digest and digest != exe_hash:
        raise SystemExit(f"uploaded {ASSET} digest {digest} != local sha256:{exe_hash}")
    if not digest and asset_sha256(tok, exe_asset) != exe_hash:
        raise SystemExit(f"uploaded {ASSET} bytes do not match local sha256:{exe_hash}")
    check_checksum_text(api_asset_bytes(tok, checksum_asset, limit=4096), exe_hash)
    print(
        f"Draft verified remotely: commit {head[:12]}, "
        f"{ASSET} {exe_size} bytes; checksum PASS"
    )
    return release


def publish(tok, release: dict, tag: str, head: str, exe_hash: str, exe_size: int):
    # Re-fetch and revalidate immediately before the externally visible publish.
    verify_draft(tok, tag, head, exe_hash, exe_size, release["id"])
    fetch_origin()
    check_release_branch()
    check_tag_provenance(tag.removeprefix("v"))
    check_clean_tree()
    published = api(
        f"/repos/{REPO}/releases/{release['id']}",
        tok,
        data=json.dumps({"draft": False}).encode(),
        method="PATCH",
    )
    if published is None or published.get("draft"):
        raise SystemExit(f"GitHub did not publish draft {tag}")
    return published


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


def verify_public_download(asset: dict, exe_hash: str, exe_size: int) -> None:
    url = asset.get("browser_download_url")
    if not url:
        raise SystemExit(f"published asset {ASSET} has no download URL")
    # Public assets need no credential; do not forward the API token through redirects.
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url)) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"could not download public {ASSET} ({exc.code})")
    actual = digest.hexdigest()
    if size != exe_size:
        raise SystemExit(f"public {ASSET} size {size} != local {exe_size}")
    if actual != exe_hash:
        raise SystemExit(f"public {ASSET} sha256 {actual} != local {exe_hash}")
    print(f"Public download verified: {ASSET} size {size}, SHA256 {actual}")


def verify_public_release(tok, tag: str, head: str, exe_hash: str, exe_size: int) -> dict:
    release = api(f"/repos/{REPO}/releases/tags/{tag}", tok)
    if release is None or release.get("draft"):
        raise SystemExit(f"published release {tag} is missing or still a draft")
    if release.get("tag_name") != tag:
        raise SystemExit(f"published release tag {release.get('tag_name')!r} != {tag!r}")
    target = (release.get("target_commitish") or "").strip()
    if target != head:
        raise SystemExit(f"published target_commitish {target!r} != release commit {head!r}")
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    exe_asset = assets.get(ASSET)
    checksum_asset = assets.get(ASSET_SHA)
    if exe_asset is None or checksum_asset is None:
        raise SystemExit("published release is missing required assets")
    if exe_asset.get("size") != exe_size:
        raise SystemExit(f"published {ASSET} size {exe_asset.get('size')} != local {exe_size}")
    digest = (exe_asset.get("digest") or "").removeprefix("sha256:")
    if digest and digest != exe_hash:
        raise SystemExit(f"published {ASSET} digest {digest} != local sha256:{exe_hash}")
    if not digest and asset_sha256(tok, exe_asset) != exe_hash:
        raise SystemExit(f"published {ASSET} bytes do not match local sha256:{exe_hash}")
    check_checksum_text(api_asset_bytes(tok, checksum_asset, limit=4096), exe_hash)
    verify_published_tag(tok, tag, head)
    verify_public_download(exe_asset, exe_hash, exe_size)
    print(f"Public release verified: {release.get('html_url', tag)}")
    return release


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
    checksum = checksum_blob(exe_hash)

    token = get_token()
    release = ensure_draft(token, tag, head, notes)
    release = fetch_draft(token, tag, head, release["id"])
    upload_asset(token, release, ASSET, blob, "application/octet-stream")
    release = fetch_draft(token, tag, head, release["id"])
    upload_asset(token, release, ASSET_SHA, checksum, "text/plain")
    verify_draft(token, tag, head, exe_hash, len(blob), release["id"])
    published = publish(token, release, tag, head, exe_hash, len(blob))
    public = verify_public_release(token, tag, head, exe_hash, len(blob))
    assets = {asset["name"]: asset for asset in public.get("assets", [])}
    print(f"Published {public.get('html_url', published.get('html_url', tag))}")
    print(f"Download: {assets[ASSET].get('browser_download_url', '')}")


if __name__ == "__main__":
    main()
