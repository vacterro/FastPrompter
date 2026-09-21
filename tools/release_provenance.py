"""Release provenance: accepted-RC manifest, release receipt, exact identity.

This module is the single owner of the release identity contract:

- the canonical release-critical file set and its deterministic fingerprint;
- the EXE identity (SHA256, size, ProductVersion) of a built artifact;
- the ACCEPTED RC manifest (frozen before any Git staging);
- the release receipt (written after commit + build + probe) and its
  verification that binds receipt -> VERSION -> commit -> EXE.

tools/release.py refuses to publish without a receipt that passes
``verify_receipt`` on all four binds (version, commit, EXE hash,
ProductVersion). tools/build.py and tools/probe_release.py record their
evidence under build/ where this module reads it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = REPO_ROOT / "build" / "accepted_rc_manifest.json"
RECEIPT_PATH = REPO_ROOT / "build" / "release_receipt.json"
BUILD_REPORT_PATH = REPO_ROOT / "build" / "build_report.json"
PROBE_RESULT_PATH = REPO_ROOT / "build" / "probe_release_result.json"

FINGERPRINT_SCHEME = "release-source-v1"

#: Release-critical single files at the repository root (handoff freeze list).
SOURCE_ROOT_FILES = (
    "FastPrompter.pyw",
    "VERSION",
    "pyproject.toml",
    "uv.lock",
)

#: Release-critical tooling (executed or shipped by the release pipeline).
SOURCE_TOOL_FILES = (
    "tools/build.py",
    "tools/probe_release.py",
    "tools/release.py",
    "tools/release_provenance.py",
    "tools/sync_release_version.py",
    "tools/set_default_from_current.py",
)

#: Nuitka-included resource trees outside src/ (src/fastprompter/** is walked).
SOURCE_RESOURCE_DIRS = ("_res",)

_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}


class ProvenanceError(RuntimeError):
    """Explicit release-identity failure (never an assert)."""


def read_version(root: Path = REPO_ROOT) -> str:
    """Canonical version: VERSION file first, pyproject fallback for legacy callers."""
    vfile = root / "VERSION"
    try:
        value = vfile.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"\d+\.\d+\.\d+", value):
            return value
    except OSError:
        pass
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise ProvenanceError("version not found in pyproject.toml")
    return match.group(1)


def check_version_parity(version: str, root: Path = REPO_ROOT) -> None:
    """Every version owner must agree with the canonical VERSION value."""
    pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.M)
    pyproject_ver = match.group(1) if match else None

    pyw_text = (root / "FastPrompter.pyw").read_text(encoding="utf-8")
    match = re.search(r"--product-version=(\S+)", pyw_text)
    pyw_ver = match.group(1) if match else None

    lock_text = (root / "uv.lock").read_text(encoding="utf-8")
    match = re.search(r'name = "fastprompter"\s+version = "([^"]+)"', lock_text)
    lock_ver = match.group(1) if match else None

    mismatches = []
    if pyproject_ver != version:
        mismatches.append(f"pyproject.toml {pyproject_ver} != VERSION {version}")
    if pyw_ver != version:
        mismatches.append(f"FastPrompter.pyw {pyw_ver} != VERSION {version}")
    if lock_ver != version:
        mismatches.append(f"uv.lock {lock_ver} != VERSION {version}")
    if mismatches:
        raise ProvenanceError(
            "version parity failed: "
            + "; ".join(mismatches)
            + " -- run python tools/sync_release_version.py"
        )


def git(*args: str, root: Path = REPO_ROOT, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise ProvenanceError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    return proc.stdout.strip()


def git_head(root: Path = REPO_ROOT) -> str:
    return git("rev-parse", "HEAD", root=root)


def git_branch(root: Path = REPO_ROOT) -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD", root=root)


def git_is_clean(root: Path = REPO_ROOT) -> bool:
    return git("status", "--porcelain=v2", "--untracked-files=normal", root=root) == ""


def git_remote_tag_commit(tag: str, remote: str = "origin", root: Path = REPO_ROOT) -> str | None:
    """Peeled commit of a REMOTE tag, or None when the remote has no such tag.

    Network/remote failure raises ProvenanceError -- an unverifiable remote is
    never treated as 'tag absent'.
    """
    out = git("ls-remote", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}", root=root)
    plain = None
    peeled = None
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref.endswith("^{}"):
            peeled = sha.strip()
        else:
            plain = sha.strip()
    return peeled or plain


def release_file_set(root: Path = REPO_ROOT) -> list[str]:
    """Deterministic release-critical path list (POSIX separators, sorted)."""
    files: set[str] = set()
    for name in SOURCE_ROOT_FILES:
        if (root / name).is_file():
            files.add(name)
    for name in SOURCE_TOOL_FILES:
        if (root / name).is_file():
            files.add(name)
    src = root / "src" / "fastprompter"
    if src.is_dir():
        for path in src.rglob("*"):
            if path.is_file() and not any(part in _SKIP_DIR_NAMES for part in path.parts):
                files.add(path.relative_to(root).as_posix())
    for dirname in SOURCE_RESOURCE_DIRS:
        base = root / dirname
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and not any(part in _SKIP_DIR_NAMES for part in path.parts):
                    files.add(path.relative_to(root).as_posix())
    return sorted(files)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(paths: list[str], root: Path = REPO_ROOT) -> str:
    """Deterministic digest over (path, content-hash) pairs."""
    digest = hashlib.sha256()
    for rel in paths:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(root / rel).encode("ascii"))
        digest.update(b"\n")
    return f"{FINGERPRINT_SCHEME}:{digest.hexdigest()}"


def default_profile_digest(root: Path = REPO_ROOT) -> str:
    path = root / "src" / "fastprompter" / "core" / "default_profile.py"
    if not path.is_file():
        return ""
    return sha256_file(path)


def exe_product_version(exe_path: Path) -> str:
    """ProductVersion from the PE version resource (Windows only, '' elsewhere)."""
    if os.name != "nt":
        return ""
    import ctypes

    path = os.path.abspath(str(exe_path))
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buffer):
        return ""
    value_ptr = ctypes.c_void_p()
    value_len = ctypes.c_uint()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(value_ptr), ctypes.byref(value_len)):
        return ""

    class FixedFileInfo(ctypes.Structure):
        _fields_ = (
            ("dwSignature", ctypes.c_uint32),
            ("dwStrucVersion", ctypes.c_uint32),
            ("dwFileVersionMS", ctypes.c_uint32),
            ("dwFileVersionLS", ctypes.c_uint32),
            ("dwProductVersionMS", ctypes.c_uint32),
            ("dwProductVersionLS", ctypes.c_uint32),
        )

    info = ctypes.cast(value_ptr, ctypes.POINTER(FixedFileInfo)).contents
    ms, ls = info.dwProductVersionMS, info.dwProductVersionLS
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def exe_identity(exe_path: Path) -> dict:
    if not Path(exe_path).is_file():
        raise ProvenanceError(f"EXE not found: {exe_path}")
    path = Path(exe_path)
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "product_version": exe_product_version(path),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def release_identity(root: Path = REPO_ROOT) -> dict:
    paths = release_file_set(root)
    return {
        "version": read_version(root),
        "head": git_head(root),
        "branch": git_branch(root),
        "tree_fingerprint": source_fingerprint(paths, root),
        "file_count": len(paths),
        "default_profile_sha256": default_profile_digest(root),
    }


def freeze_accepted_manifest(
    exe_path: Path,
    out_path: Path = MANIFEST_PATH,
    suite_result: str = "",
    operator_acceptance: str = "",
    root: Path = REPO_ROOT,
) -> dict:
    identity = release_identity(root)
    paths = release_file_set(root)
    manifest = {
        "schema_version": 1,
        "operation": "accepted_rc_manifest",
        "recorded_at": _now(),
        "version": identity["version"],
        "source_head": identity["head"],
        "branch": identity["branch"],
        "source_tree_fingerprint": identity["tree_fingerprint"],
        "file_count": identity["file_count"],
        "file_hashes": {rel: sha256_file(root / rel) for rel in paths},
        "default_profile_sha256": identity["default_profile_sha256"],
        "exe": exe_identity(exe_path),
        "full_suite_result": suite_result,
        "operator_manual_acceptance": {
            "status": "ACCEPTED" if operator_acceptance else "UNRECORDED",
            "reference": operator_acceptance,
            "recorded_at": _now() if operator_acceptance else "",
        },
    }
    _write_json(out_path, manifest)
    return manifest


def write_receipt(
    exe_path: Path,
    out_path: Path = RECEIPT_PATH,
    suite_result: str = "",
    operator_acceptance: str = "",
    commit: str | None = None,
    root: Path = REPO_ROOT,
) -> dict:
    """Bind source + EXE + evidence into a receipt for release.py to verify."""
    identity = release_identity(root)
    head = commit or identity["head"]
    build_report = _read_json(BUILD_REPORT_PATH)
    probe_result = _read_json(PROBE_RESULT_PATH)
    if not suite_result:
        suite_result = str(_read_json(root / "build" / "ci_gate_result.json").get("summary", ""))
    if not operator_acceptance:
        acceptance_file = root / "build" / "operator_acceptance.txt"
        if acceptance_file.is_file():
            operator_acceptance = acceptance_file.read_text(encoding="utf-8").strip()
    if not build_report:
        raise ProvenanceError(
            f"build report missing ({BUILD_REPORT_PATH}); run tools/build.py first"
        )
    if not probe_result:
        raise ProvenanceError(
            f"probe result missing ({PROBE_RESULT_PATH}); run tools/probe_release.py first"
        )
    if not probe_result.get("ok"):
        raise ProvenanceError("packaged probe did not pass; refusing a receipt")
    if not suite_result:
        raise ProvenanceError("full-suite result is required for a release receipt")
    if not operator_acceptance:
        raise ProvenanceError("operator manual acceptance statement is required")

    exe = exe_identity(exe_path)
    if probe_result.get("exe_sha256") != exe["sha256"]:
        raise ProvenanceError(
            "probe result does not describe this EXE "
            f"(probe {probe_result.get('exe_sha256')}, exe {exe['sha256']})"
        )
    if git_head(root) != head:
        raise ProvenanceError(f"receipt commit {head} is not HEAD ({git_head(root)})")
    if not git_is_clean(root):
        raise ProvenanceError("working tree is dirty; a receipt binds a clean release commit")

    receipt = {
        "schema_version": 1,
        "operation": "release_receipt",
        "version": identity["version"],
        "tag": f"v{identity['version']}",
        "release_commit": head,
        "branch": identity["branch"],
        "source_tree_fingerprint": identity["tree_fingerprint"],
        "default_profile_sha256": identity["default_profile_sha256"],
        "exe_sha256": exe["sha256"],
        "exe_size": exe["size"],
        "product_version": exe["product_version"],
        "build_toolchain": build_report.get("toolchain", {}),
        "verification": {
            "full_suite": suite_result,
            "build": build_report.get("result", ""),
        },
        "probe": probe_result,
        "operator_manual_acceptance": {
            "status": "ACCEPTED",
            "reference": operator_acceptance,
            "recorded_at": _now(),
        },
        "recorded_at": _now(),
    }
    _write_json(out_path, receipt)
    return receipt


def validate_receipt(
    receipt: dict,
    exe_path: Path,
    version: str,
    commit: str,
) -> list[str]:
    """The four binds release.py refuses to publish without."""
    failures: list[str] = []
    if receipt.get("version") != version:
        failures.append(f"receipt version {receipt.get('version')!r} != VERSION {version!r}")
    if receipt.get("release_commit") != commit:
        failures.append(f"receipt commit {receipt.get('release_commit')!r} != HEAD {commit!r}")
    if not Path(exe_path).is_file():
        failures.append(f"EXE missing: {exe_path}")
        return failures
    exe_hash = sha256_file(Path(exe_path))
    if receipt.get("exe_sha256") != exe_hash:
        failures.append(f"receipt EXE sha256 {receipt.get('exe_sha256')!r} != {exe_hash!r}")
    product_version = exe_product_version(Path(exe_path))
    if receipt.get("product_version") != product_version:
        failures.append(
            f"receipt ProductVersion {receipt.get('product_version')!r} != {product_version!r}"
        )
    return failures


def compare_manifest_to_tree(manifest_path: Path, root: Path = REPO_ROOT) -> list[str]:
    """Release-critical hash differences between a frozen manifest and a tree."""
    manifest = _read_json(manifest_path)
    if not manifest.get("file_hashes"):
        raise ProvenanceError(f"manifest has no file hashes: {manifest_path}")
    differences: list[str] = []
    recorded: dict = manifest["file_hashes"]
    for rel, expected in sorted(recorded.items()):
        target = root / rel
        if not target.is_file():
            differences.append(f"MISSING {rel}")
            continue
        actual = sha256_file(target)
        if actual != expected:
            differences.append(f"CHANGED {rel}")
    current = set(release_file_set(root))
    for rel in sorted(current - set(recorded)):
        differences.append(f"ADDED {rel}")
    return differences


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("identity", "freeze", "receipt", "verify", "compare"))
    parser.add_argument("--exe", default=str(REPO_ROOT / "build" / "FastPrompter.exe"))
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--out", default="")
    parser.add_argument("--suite-result", default="")
    parser.add_argument("--operator-acceptance", default="")
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)

    try:
        if args.action == "identity":
            print(json.dumps(release_identity(), indent=2))
            return 0
        if args.action == "freeze":
            manifest = freeze_accepted_manifest(
                Path(args.exe),
                Path(args.out) if args.out else MANIFEST_PATH,
                suite_result=args.suite_result,
                operator_acceptance=args.operator_acceptance,
            )
            print(
                f"frozen manifest: {manifest['source_tree_fingerprint']} "
                f"({manifest['file_count']} files, EXE sha256 {manifest['exe']['sha256'][:16]}...)"
            )
            return 0
        if args.action == "receipt":
            receipt = write_receipt(
                Path(args.exe),
                Path(args.out) if args.out else RECEIPT_PATH,
                suite_result=args.suite_result,
                operator_acceptance=args.operator_acceptance,
                commit=args.commit or None,
            )
            print(
                f"receipt written: v{receipt['version']} commit {receipt['release_commit'][:12]} "
                f"EXE sha256 {receipt['exe_sha256'][:16]}..."
            )
            return 0
        if args.action == "verify":
            receipt = _read_json(Path(args.out) if args.out else RECEIPT_PATH)
            if not receipt:
                print(f"FAIL receipt missing or unreadable: {args.out or RECEIPT_PATH}")
                return 1
            failures = validate_receipt(
                receipt, Path(args.exe), read_version(), git_head()
            )
            if failures:
                for failure in failures:
                    print(f"FAIL {failure}")
                return 1
            print("receipt binds VERSION, commit, EXE sha256 and ProductVersion: PASS")
            return 0
        if args.action == "compare":
            differences = compare_manifest_to_tree(
                Path(args.manifest if args.manifest else MANIFEST_PATH)
            )
            if not differences:
                print("release-critical tree matches the frozen manifest: PASS")
                return 0
            for difference in differences:
                print(difference)
            return 1
    except ProvenanceError as exc:
        print(f"FAIL {exc}")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
