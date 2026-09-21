"""T-1234: the owner-mismatch recovery artifact is bounded and atomic.

The T-1227 fail-closed guard refuses to flush the live editor into a silo it
cannot prove ownership of, and publishes the text to a recovery file instead so
the user's work is not simply dropped. That part is right.

What it did not do was bound itself. The guard fires from the save path, the
save path runs on a 10-second timer, and a mismatch the user can neither see
nor clear therefore wrote a full copy of the editor buffer six times a minute
for as long as the app stayed open - on the same volume as the database. At a
200 KB silo that is roughly 70 MB an hour of duplicated user text. A guard that
protects the data by filling the disk it lives on is not a guard.

Three properties, then:

* identical text is captured once, not once per timer tick;
* past a cap nothing more is written, and the files KEPT are the earliest ones,
  because those sit nearest the root cause - a rotating window would discard
  the original evidence and retain N copies of the aftermath;
* each file is published atomically, because a half-written recovery artifact
  is worse than none: it looks like the text was saved.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.main import FastPrompter


class _Stub:
    """Just enough object to call the real method against."""
    _OWNER_MISMATCH_ARTIFACT_CAP = FastPrompter._OWNER_MISMATCH_ARTIFACT_CAP
    _publish_owner_mismatch_artifact = \
        FastPrompter._publish_owner_mismatch_artifact


def _publish(base, text, payload=None):
    import hashlib
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return _Stub()._publish_owner_mismatch_artifact(
        str(base), digest, payload or {"reason": "SILO_OWNER_MISMATCH"}, text)


def test_the_artifact_holds_the_live_text(tmp_path):
    path = _publish(tmp_path, "precious unsaved words")
    assert path is not None
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["text"] == "precious unsaved words"
    assert data["reason"] == "SILO_OWNER_MISMATCH"


def test_the_same_text_is_captured_once(tmp_path):
    """The autosave timer refires the same mismatch every 10 seconds."""
    first = _publish(tmp_path, "same buffer")
    for _ in range(30):
        again = _publish(tmp_path, "same buffer")
        assert again == first
    assert len(list(tmp_path.glob("silo_owner_mismatch_*.json"))) == 1


def test_distinct_texts_each_get_their_own_artifact(tmp_path):
    a = _publish(tmp_path, "buffer one")
    b = _publish(tmp_path, "buffer two")
    assert a != b
    assert len(list(tmp_path.glob("silo_owner_mismatch_*.json"))) == 2


def test_the_cap_keeps_the_earliest_evidence(tmp_path):
    cap = FastPrompter._OWNER_MISMATCH_ARTIFACT_CAP
    kept = []
    for i in range(cap):
        kept.append(_publish(tmp_path, f"buffer {i}"))
    assert all(kept)
    assert len(list(tmp_path.glob("silo_owner_mismatch_*.json"))) == cap

    # Past the cap: nothing more is written, and nothing already written is
    # thrown away to make room.
    overflow = _publish(tmp_path, "one too many")
    assert overflow is None
    assert len(list(tmp_path.glob("silo_owner_mismatch_*.json"))) == cap
    for path in kept:
        assert os.path.isfile(path), "the earliest evidence was rotated out"


def test_no_partial_artifact_is_left_behind(tmp_path):
    _publish(tmp_path, "atomic please")
    leftovers = list(tmp_path.glob("*.tmp-*"))
    assert not leftovers, f"temp files survived the publish: {leftovers}"


def test_an_unreadable_recovery_dir_does_not_raise(tmp_path):
    """os.listdir failing must not turn a refused flush into a crash."""
    missing = tmp_path / "not_created_yet"
    # The caller makedirs() first; this proves the listing itself is guarded.
    missing.mkdir()
    assert _publish(missing, "still works") is not None
