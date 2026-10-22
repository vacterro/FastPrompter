"""T-1437 (SRC-097) — PERF-004: deep reuse verification is bounded and single-pass.

A candidate whose size/mtime no longer match its history is deep-verified: every
member is read to EOF (so ``ZipExtFile`` still checks its CRC, the guarantee
``testzip()`` used to provide) and manifest members accumulate a SHA-256, with
memory bounded by ``_VERIFY_CHUNK_BYTES`` instead of the largest member.
"""

from __future__ import annotations

import hashlib
import json
import zipfile

from fastprompter.core import silo_bundle as sb


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(path, members, hashes, fingerprint="fp-1"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema_version": 6,
            "content_fingerprint": fingerprint,
            "hashes": hashes,
        }))
        for name, data in members.items():
            zf.writestr(name, data)


def test_perf_004_deep_verify_accepts_a_matching_archive(tmp_path):
    p = tmp_path / "b.zip"
    payload = b"hello world"
    _zip(p, {"media/a.bin": payload}, {"media/a.bin": _sha(payload)})

    # wrong recorded mtime forces the deep path
    assert sb.verify_reuse_candidate(str(p), "fp-1", None, 1) is True


def test_perf_004_deep_verify_rejects_a_wrong_hash(tmp_path):
    p = tmp_path / "b.zip"
    _zip(p, {"media/a.bin": b"hello"}, {"media/a.bin": _sha(b"different")})

    assert sb.verify_reuse_candidate(str(p), "fp-1", None, 1) is False


def test_perf_004_deep_verify_rejects_a_missing_manifest_member(tmp_path):
    p = tmp_path / "b.zip"
    _zip(p, {"media/a.bin": b"hello"},
         {"media/a.bin": _sha(b"hello"), "media/gone.bin": _sha(b"x")})

    assert sb.verify_reuse_candidate(str(p), "fp-1", None, 1) is False


def test_perf_004_deep_verify_streams_a_member_larger_than_one_chunk(tmp_path):
    p = tmp_path / "b.zip"
    chunk = sb._VERIFY_CHUNK_BYTES
    big = b"z" * (2 * chunk + 7)          # 2+ chunks, no manifest hash
    scored = b"payload"
    _zip(p, {"media/big.bin": big, "media/a.bin": scored},
         {"media/a.bin": _sha(scored)})

    assert sb.verify_reuse_candidate(str(p), "fp-1", None, 1) is True


def test_perf_004_chunk_is_bounded():
    assert 0 < sb._VERIFY_CHUNK_BYTES <= (1 << 20)
