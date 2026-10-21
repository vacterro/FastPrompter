"""Inspect the built FastPrompter EXE, not the source tree that fed it.

Why this exists
---------------
``tools/verify_sound_allowlist.py`` answers "what would a push publish?" -- a
source question.  A release ships ``build/FastPrompter.exe``, which is a
different set of bytes: Nuitka globs a directory into a compressed payload, and
a stale build directory, a snapshot subfolder or a file the packager picked up
from somewhere else never appears in the source answer.  The historical
contamination looked exactly like that: ``sound/_vault/`` sat inside the
packaged folder with 536 third-party WAVs in it while the source allowlist was
green.

This tool reads the payload out of the finished EXE and holds it to the source
tree: every audio entry must be byte-identical to a file in
``src/fastprompter/sound/``, and that set is exactly the allowlisted set.  No
audio entry may live outside the ``sound/`` prefix.  A file with no source
counterpart is a failure, not a warning: nothing in the build may invent audio.

Modes
-----
``artifact``   Examine a built EXE.  Default.
``acceptance`` Additionally require a passing packaged-probe result and a
               release receipt that binds this exact EXE hash.  This is the
               mode a release runs; ``artifact`` alone is not release evidence.

Fail-closed: if the payload cannot be decompressed, the tool exits 2 and says
so.  A release gate that silently passes when it cannot see inside the artifact
is worse than no gate.

Usage:
    python tools/audit_release_artifact.py [--exe build/FastPrompter.exe]
    python tools/audit_release_artifact.py --mode acceptance
    python tools/audit_release_artifact.py --payload-file fixture.bin  # red controls

Exit codes: 0 pass, 1 rejected (a named finding), 2 tool failure / unreadable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOUNDS_REL = Path("src/fastprompter/sound")
MANIFEST_REL = Path("sounds-redistributable.manifest")
AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".m4a"}
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
DEFAULT_EXE = PROJECT_ROOT / "build" / "FastPrompter.exe"
PROBE_RESULT = PROJECT_ROOT / "build" / "probe_release_result.json"
RECEIPT = PROJECT_ROOT / "build" / "release_receipt.json"


class UnreadableArtifact(RuntimeError):
    """The payload could not be recovered; the gate must not pass."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_from_exe(exe: Path) -> bytes:
    """Recover Nuitka's onefile payload without executing the binary.

    The bootstrap appends a zstd frame whose decompressed content is a flat
    stream of ``<utf-16le name><u16 0><u64 size><data>`` entries.  Every zstd
    magic offset is tried because the frame does not start at a fixed place.
    """
    try:
        import zstandard
    except ImportError as exc:  # noqa: TRY003 - the message names the fix
        raise UnreadableArtifact(
            "zstandard is required to inspect the onefile payload; "
            "install it with: pip install zstandard"
        ) from exc

    blob = exe.read_bytes()
    start = 0
    while True:
        at = blob.find(ZSTD_MAGIC, start)
        if at < 0:
            break
        start = at + 1
        try:
            candidate = zstandard.ZstdDecompressor().decompressobj().decompress(blob[at:])
        except zstandard.ZstdError:
            continue
        if b".wav" in candidate[:4000] or b"MZ" in candidate[:200]:
            return candidate
    raise UnreadableArtifact(f"no Nuitka onefile zstd payload found in {exe}")


def parse_payload(payload: bytes) -> list[tuple[str, bytes]]:
    """Walk the flat entry stream; stop at the first entry that does not parse."""
    entries: list[tuple[str, bytes]] = []
    pos = 0
    while pos + 2 <= len(payload):
        end = pos
        while end + 1 < len(payload) and not (payload[end] == 0 and payload[end + 1] == 0):
            end += 2
        if end == pos:
            break
        try:
            name = payload[pos:end].decode("utf-16-le")
        except UnicodeDecodeError:
            break
        cursor = end + 2
        if cursor + 8 > len(payload):
            break
        size = struct.unpack_from("<Q", payload, cursor)[0]
        cursor += 8
        if cursor + size > len(payload):
            break
        entries.append((name, payload[cursor:cursor + size]))
        pos = cursor + size
    return entries


def source_audio(root: Path) -> dict[str, str]:
    """rel path -> sha256 for every WAV in the shipped sound folder."""
    sounds = root / SOUNDS_REL
    if not sounds.is_dir():
        raise UnreadableArtifact(f"shipped sound folder missing: {sounds}")
    return {
        path.relative_to(sounds).as_posix().lower(): sha256_file(path)
        for path in sounds.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
    }


def allowlisted_names(root: Path) -> set[str]:
    manifest = root / MANIFEST_REL
    if not manifest.is_file():
        raise UnreadableArtifact(f"sound allowlist missing: {manifest}")
    names = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.replace("\\", "/").lower())
    return names


def normalise_entry_name(name: str) -> str:
    """Nuitka writes ``sound\\foo.wav``; compare on the part below ``sound/``."""
    clean = name.replace("\\", "/")
    marker = "sound/"
    at = clean.lower().find(marker)
    return clean[at + len(marker):].lower() if at >= 0 else clean.lower()


def audit_payload(payload: bytes, root: Path) -> dict:
    """Classify every audio entry in the payload against the source tree."""
    entries = parse_payload(payload)
    if not entries:
        # A payload that yields no entries is unreadable, not clean. Without
        # this the "nothing shipped" case would satisfy every loop below.
        raise UnreadableArtifact("payload parsed to zero entries; refusing to read that as clean")
    audio = [(name, data) for name, data in entries if Path(name).suffix.lower() in AUDIO_SUFFIXES]
    expected = source_audio(root)
    allowed = allowlisted_names(root)

    findings: list[dict] = []
    seen: dict[str, str] = {}
    for name, data in audio:
        rel = normalise_entry_name(name)
        digest = sha256_bytes(data)
        where = "/".join(name.replace("\\", "/").split("/")[:-1]).lower()
        if "sound" not in where.split("/"):
            findings.append({"kind": "AUDIO_OUTSIDE_SOUND_TREE", "entry": name})
            continue
        if rel not in expected:
            findings.append({"kind": "AUDIO_NOT_IN_SOURCE_TREE", "entry": name, "sha256": digest})
            continue
        if digest != expected[rel]:
            findings.append({
                "kind": "PAYLOAD_DIFFERS_FROM_SOURCE",
                "entry": name,
                "payload_sha256": digest,
                "source_sha256": expected[rel],
            })
            continue
        if rel not in allowed:
            findings.append({"kind": "SHIPPED_BUT_NOT_ALLOWLISTED", "entry": name})
            continue
        seen[rel] = digest

    # Both directions of allowlist drift, reported separately because they call
    # for different fixes: a manifest row with no file is a stale row, a source
    # file with no manifest row is an unvetted file that will ship next build.
    for rel in sorted(allowed - set(expected)):
        findings.append({"kind": "ALLOWLIST_NAMES_A_FILE_WITHOUT_SOURCE", "entry": rel})
    for rel in sorted(set(expected) - allowed):
        findings.append({"kind": "SOURCE_SOUND_NOT_ALLOWLISTED", "entry": rel})
    for rel in sorted(set(expected) - set(seen)):
        findings.append({"kind": "SOURCE_SOUND_NOT_IN_PAYLOAD", "entry": rel})

    return {
        "mode": "artifact",
        "payload_entries": len(entries),
        "audio_entries": len(audio),
        "source_sounds": len(expected),
        "allowlist_entries": len(allowed),
        "findings": findings,
        "ok": not findings,
    }


def require_acceptance_evidence(exe_hash: str) -> list[dict]:
    """A passing probe and a receipt bound to this hash; names what is missing."""
    findings: list[dict] = []
    if not PROBE_RESULT.is_file():
        findings.append({"kind": "PROBE_RESULT_MISSING", "path": str(PROBE_RESULT)})
    else:
        probe = json.loads(PROBE_RESULT.read_text(encoding="utf-8"))
        if probe.get("ok") is not True:
            findings.append({"kind": "PACKAGED_PROBE_NOT_PASSING", "path": str(PROBE_RESULT)})
        elif probe.get("exe_sha256") != exe_hash:
            findings.append({
                "kind": "PROBE_MEASURED_ANOTHER_EXE",
                "probe_sha256": probe.get("exe_sha256"),
                "artifact_sha256": exe_hash,
            })
    if not RECEIPT.is_file():
        findings.append({"kind": "RELEASE_RECEIPT_MISSING", "path": str(RECEIPT)})
    else:
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if receipt.get("exe_sha256") != exe_hash:
            findings.append({
                "kind": "RECEIPT_BINDS_ANOTHER_EXE",
                "receipt_sha256": receipt.get("exe_sha256"),
                "artifact_sha256": exe_hash,
            })
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("artifact", "acceptance"), default="artifact")
    parser.add_argument("--exe", default=str(DEFAULT_EXE))
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--payload-file",
                        help="inspect a raw payload stream instead of an EXE (red-control fixtures)")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        if args.payload_file:
            payload = Path(args.payload_file).read_bytes()
            report = audit_payload(payload, root)
            report["artifact"] = str(Path(args.payload_file).resolve())
            report["artifact_sha256"] = sha256_bytes(payload)
        else:
            exe = Path(args.exe).resolve()
            if not exe.is_file():
                raise UnreadableArtifact(f"built EXE missing: {exe} (run tools/build.py first)")
            payload = payload_from_exe(exe)
            report = audit_payload(payload, root)
            report["artifact"] = str(exe)
            report["artifact_sha256"] = sha256_file(exe)
            report["artifact_size"] = exe.stat().st_size
            if args.mode == "acceptance":
                report["mode"] = "acceptance"
                extra = require_acceptance_evidence(report["artifact_sha256"])
                report["findings"].extend(extra)
                report["ok"] = not report["findings"]
    except UnreadableArtifact as exc:
        report = {"ok": False, "error": str(exc), "findings": [{"kind": "UNREADABLE_ARTIFACT"}]}
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"FAIL {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - the receipt records the failure
        report = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "findings": [{"kind": "TOOL_FAILURE"}]}
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"FAIL {type(exc).__name__}: {exc}")
        return 2

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not report["ok"]:
        print(f"FAIL artifact rejected: {len(report['findings'])} finding(s)")
        for finding in report["findings"][:20]:
            detail = ", ".join(f"{k}={v}" for k, v in finding.items() if k != "kind")
            print(f"  {finding['kind']}: {detail}")
        return 1

    print(f"PASS artifact inspection: {report['audio_entries']} audio entries, "
          f"{report['payload_entries']} payload entries, all byte-identical to the "
          f"allowlisted source tree")
    if args.mode == "acceptance":
        print("PASS release acceptance: probe result and receipt bind this EXE hash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
