"""Red controls for ``tools/audit_release_artifact.py``.

The gate exists because the source allowlist was green while 536 third-party
WAVs rode inside ``sound/_vault/`` in a published EXE. A detector that has only
ever seen a good build proves nothing, so each test here builds the payload
Nuitka would produce and requires the gate to name the defect:

* audio outside ``sound/``                     -> AUDIO_OUTSIDE_SOUND_TREE
* audio inside ``sound/`` with no source file  -> AUDIO_NOT_IN_SOURCE_TREE
* a known name whose bytes were swapped        -> PAYLOAD_DIFFERS_FROM_SOURCE
* a source sound that never made it in        -> SOURCE_SOUND_NOT_IN_PAYLOAD
* bytes that are not a payload at all          -> exit 2, never a pass
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import audit_release_artifact as gate  # noqa: E402


def payload(*entries: tuple[str, bytes]) -> bytes:
    """Nuitka's flat payload: utf-16le name, u16 NUL, u64 size, data."""
    out = bytearray()
    for name, data in entries:
        out += name.encode("utf-16-le") + b"\x00\x00"
        out += struct.pack("<Q", len(data))
        out += data
    return bytes(out)


def wav(seed: int, size: int = 128) -> bytes:
    body = bytes((i * 37 + seed) & 0xFF for i in range(size))
    header = bytearray(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    header += struct.pack("<I", 16) + b"\x01\x00\x01\x00"
    header += struct.pack("<II", 8000, 8000) + b"\x01\x00\x08\x00"
    header += b"data" + struct.pack("<I", size)
    return bytes(header) + body


def fixture_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """A repository-shaped root: two sounds, both allowlisted."""
    root = tmp_path / "repo"
    sounds = root / "src" / "fastprompter" / "sound"
    sounds.mkdir(parents=True)
    (sounds / "blip_b.wav").write_bytes(wav(1))
    (sounds / "button1.wav").write_bytes(wav(2))
    (root / "sounds-redistributable.manifest").write_text(
        "blip_b.wav\nbutton1.wav\n", encoding="utf-8"
    )
    return root


def clean_entries(root: pathlib.Path) -> list[tuple[str, bytes]]:
    return [
        (f"sound/{name}", (root / "src/fastprompter/sound" / name).read_bytes())
        for name in ("blip_b.wav", "button1.wav")
    ]


def kinds(report: dict) -> list[str]:
    return [finding["kind"] for finding in report["findings"]]


def test_a_clean_payload_passes(tmp_path):
    root = fixture_root(tmp_path)
    report = gate.audit_payload(payload(*clean_entries(root)), root)
    assert report["ok"] is True, report["findings"]
    assert report["audio_entries"] == 2
    assert report["source_sounds"] == 2


def test_audio_outside_the_sound_folder_is_rejected(tmp_path):
    root = fixture_root(tmp_path)
    leak = ("assets/genie.wav", wav(99))
    report = gate.audit_payload(payload(*clean_entries(root), leak), root)
    assert report["ok"] is False
    assert "AUDIO_OUTSIDE_SOUND_TREE" in kinds(report)
    assert "genie.wav" in json.dumps(report["findings"])


def test_a_vault_subtree_inside_the_sound_folder_is_rejected(tmp_path):
    # The exact historical shape: ``sound/_vault/`` rode along inside the
    # packaged sound folder, so the path still starts with ``sound``.
    root = fixture_root(tmp_path)
    report = gate.audit_payload(payload(*clean_entries(root), ("sound/_vault/cs_style/x.wav", wav(96))), root)
    assert report["ok"] is False
    assert "AUDIO_NOT_IN_SOURCE_TREE" in kinds(report)


def test_audio_with_no_source_counterpart_is_rejected(tmp_path):
    root = fixture_root(tmp_path)
    report = gate.audit_payload(payload(*clean_entries(root), ("sound/smuggled.wav", wav(98))), root)
    assert report["ok"] is False
    assert "AUDIO_NOT_IN_SOURCE_TREE" in kinds(report)


def test_swapped_bytes_under_a_known_name_are_rejected(tmp_path):
    root = fixture_root(tmp_path)
    entries = clean_entries(root)
    entries[0] = ("sound/blip_b.wav", wav(97))
    report = gate.audit_payload(payload(*entries), root)
    assert report["ok"] is False
    assert "PAYLOAD_DIFFERS_FROM_SOURCE" in kinds(report)


def test_a_source_sound_missing_from_the_payload_is_rejected(tmp_path):
    root = fixture_root(tmp_path)
    report = gate.audit_payload(payload(clean_entries(root)[0]), root)
    assert report["ok"] is False
    assert "SOURCE_SOUND_NOT_IN_PAYLOAD" in kinds(report)


def test_a_manifest_entry_without_a_source_file_is_rejected(tmp_path):
    root = fixture_root(tmp_path)
    manifest = root / "sounds-redistributable.manifest"
    manifest.write_text("blip_b.wav\nbutton1.wav\nghost.wav\n", encoding="utf-8")
    report = gate.audit_payload(payload(*clean_entries(root)), root)
    assert report["ok"] is False
    assert "ALLOWLIST_NAMES_A_FILE_WITHOUT_SOURCE" in kinds(report)


def test_audio_duplicated_in_a_snapshot_subtree_is_still_rejected(tmp_path):
    # The historical leak: ``sound/_vault/`` rode inside the packaged folder, so
    # the entry looked like audio "in the sound tree" while no source file
    # matched it. Identity is the relative path below sound/, not the segment.
    root = fixture_root(tmp_path)
    snapshot = ("sound/_vault/sound/blip_b.wav", wav(1))
    report = gate.audit_payload(payload(*clean_entries(root), snapshot), root)
    assert report["ok"] is False
    assert "AUDIO_NOT_IN_SOURCE_TREE" in kinds(report)
    assert any("_vault" in json.dumps(finding) for finding in report["findings"])


def test_unreadable_artifact_exits_two_and_never_passes(tmp_path, capsys):
    broken = tmp_path / "broken.bin"
    broken.write_bytes(b"not a payload")
    code = gate.main(["--payload-file", str(broken), "--root", str(fixture_root(tmp_path))])
    assert code == 2
    captured = capsys.readouterr()
    assert "FAIL" in captured.out + captured.err


def test_acceptance_mode_requires_evidence_bound_to_this_exe(tmp_path, monkeypatch):
    root = fixture_root(tmp_path)
    report = gate.audit_payload(payload(*clean_entries(root)), root)
    assert report["ok"] is True

    # No probe result or receipt yet: acceptance must refuse.
    monkeypatch.setattr(gate, "PROBE_RESULT", tmp_path / "absent_probe.json")
    monkeypatch.setattr(gate, "RECEIPT", tmp_path / "absent_receipt.json")
    findings = gate.require_acceptance_evidence("a" * 64)
    assert {"PROBE_RESULT_MISSING", "RELEASE_RECEIPT_MISSING"} <= set(
        finding["kind"] for finding in findings
    )

    # Evidence that measures another binary must not satisfy this one.
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps({"ok": True, "exe_sha256": "b" * 64}), encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"exe_sha256": "c" * 64}), encoding="utf-8")
    monkeypatch.setattr(gate, "PROBE_RESULT", probe)
    monkeypatch.setattr(gate, "RECEIPT", receipt)
    findings = gate.require_acceptance_evidence("a" * 64)
    assert {"PROBE_MEASURED_ANOTHER_EXE", "RECEIPT_BINDS_ANOTHER_EXE"} <= set(
        finding["kind"] for finding in findings
    )


@pytest.mark.parametrize("name", ["sound/blip_b.WAV", "sound\\blip_b.wav"])
def test_case_and_windows_separators_are_normalised(tmp_path, name):
    root = fixture_root(tmp_path)
    data = (root / "src/fastprompter/sound/blip_b.wav").read_bytes()
    entries = [(name, data)] + clean_entries(root)[1:]
    report = gate.audit_payload(payload(*entries), root)
    assert "AUDIO_NOT_IN_SOURCE_TREE" not in kinds(report), report["findings"]
