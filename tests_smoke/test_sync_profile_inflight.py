from tests_smoke.test_sync_async import _FakeWorker, _setup

pytest_plugins = ["tests_smoke.test_sync_async"]


def _fake_dispatch(win, monkeypatch):
    worker = _FakeWorker()
    monkeypatch.setattr(win, "_sync_ensure_worker", lambda: worker)
    return worker


def _switch_profile(win, profile_id):
    win.state.profile_id = profile_id
    win._sync_on_profile_change()


def test_old_profile_completion_releases_only_its_inflight_job(
    win, monkeypatch, tmp_path
):
    _setup(win, tmp_path)
    win.state.profile_id = 1
    worker = _fake_dispatch(win, monkeypatch)

    win.data["temp_presets"][0] = "# t\nprofile A"
    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    snap_a, gen_a = worker.dispatch.calls[0]
    assert win._sync_inflight_gen == gen_a
    assert win._sync_inflight_profile == 1

    _switch_profile(win, 2)
    assert win._sync_inflight_gen == gen_a
    assert win._sync_inflight_profile == 1

    win.data["temp_presets"][0] = "# t\nprofile B"
    win.sync_to_disk(force=True)
    snap_b = win._sync_pending
    gen_b = snap_b["gen"]

    win._sync_on_done(gen_a, snap_a, list(snap_a["files"]), [])
    assert win._sync_written == {}
    assert win._sync_inflight_gen == gen_b
    assert win._sync_inflight_profile == 2
    assert win._sync_pending is None

    win._sync_on_done(gen_b, snap_b, list(snap_b["files"]), [])
    assert win._sync_inflight_gen == 0
    assert win._sync_inflight_profile is None
    assert win._sync_completed_gen == gen_b
    assert any("profile B" in text for text in win._sync_written.values())


def test_foreign_same_generation_completion_cannot_clear_inflight(
    win, monkeypatch, tmp_path
):
    _setup(win, tmp_path)
    worker = _fake_dispatch(win, monkeypatch)
    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    snapshot, gen = worker.dispatch.calls[0]

    foreign = dict(snapshot)
    foreign["owner"] = object()
    win._sync_on_done(gen, foreign, list(foreign["files"]), [])

    assert win._sync_inflight_gen == gen
    assert win._sync_busy is True
    assert win._sync_written == {}

    win._sync_on_done(gen, snapshot, list(snapshot["files"]), [])
    assert win._sync_busy is False


def test_rapid_a_b_a_switch_keeps_newest_a_and_never_false_idles(
    win, monkeypatch, tmp_path
):
    _setup(win, tmp_path)
    win.state.profile_id = 1
    worker = _fake_dispatch(win, monkeypatch)

    win.data["temp_presets"][0] = "# t\nA old"
    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    snap_a1, gen_a1 = worker.dispatch.calls[0]

    _switch_profile(win, 2)
    win.data["temp_presets"][0] = "# t\nB"
    win.sync_to_disk(force=True)
    assert win._sync_pending.get("profile") == 2

    _switch_profile(win, 1)
    win.data["temp_presets"][0] = "# t\nA newest"
    win.sync_to_disk(force=True)
    snap_a2 = win._sync_pending
    gen_a2 = snap_a2["gen"]
    assert win._sync_busy is True

    win._sync_on_done(gen_a1, snap_a1, list(snap_a1["files"]), [])
    assert win._sync_inflight_gen == gen_a2
    assert win._sync_inflight_profile == 1
    assert worker.dispatch.calls[-1][0] is snap_a2

    win._sync_on_done(gen_a2, snap_a2, list(snap_a2["files"]), [])
    assert any("A newest" in text for text in win._sync_written.values())
    # The B final snapshot was held during the busy switch and must now be
    # drained (P0-2) instead of being dropped.
    assert win._sync_busy is True
    snap_b, gen_b = worker.dispatch.calls[-1]
    assert snap_b.get("profile") == 2
    assert snap_b["files"] != snap_a2["files"]

    win._sync_on_done(gen_b, snap_b, list(snap_b["files"]), [])
    assert win._sync_busy is False
    assert win._sync_pending_hold == {}
    # B's generation is stale by now, so its result correctly never merges
    # into the CURRENT written cache — but the snapshot itself reached the
    # worker (asserted above), which is the P0-2 guarantee.


def test_switch_while_busy_does_not_drop_final_old_profile_snapshot(
    win, monkeypatch, tmp_path
):
    """P0-2 core regression: A1 inflight, A2 final pending, switch to B —
    finishing A1 must dispatch A2, never drop it."""
    _setup(win, tmp_path)
    win.state.profile_id = 1
    worker = _fake_dispatch(win, monkeypatch)

    win.data["temp_presets"][0] = "# t\nA first"
    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    snap_a1, gen_a1 = worker.dispatch.calls[0]

    win.data["temp_presets"][0] = "# t\nA final"
    win.sync_to_disk(force=True)
    assert win._sync_pending.get("profile") == 1

    _switch_profile(win, 2)
    assert win._sync_pending is None
    assert win._sync_pending_hold.get(1) is not None
    held_a2 = win._sync_pending_hold[1]
    assert any("A final" in text for text in held_a2["files"].values())

    win.data["temp_presets"][0] = "# t\nB text"
    win.sync_to_disk(force=True)
    snap_b = win._sync_pending

    win._sync_on_done(gen_a1, snap_a1, list(snap_a1["files"]), [])
    assert win._sync_busy is True
    assert win._sync_inflight_profile == 1
    assert worker.dispatch.calls[-1][0] is held_a2

    win._sync_on_done(held_a2["gen"], held_a2, list(held_a2["files"]), [])
    assert win._sync_inflight_profile == 2
    assert worker.dispatch.calls[-1][0] is snap_b

    win._sync_on_done(snap_b["gen"], snap_b, list(snap_b["files"]), [])
    assert win._sync_busy is False
    assert any("B text" in text for text in win._sync_written.values())
    assert win._sync_pending_hold == {}


def test_switch_while_idle_dispatches_final_immediately(win, monkeypatch, tmp_path):
    """P0-2: when the worker is idle the final snapshot dispatches right
    away, exactly like before — no hold, no pending."""
    _setup(win, tmp_path)
    win.state.profile_id = 1
    worker = _fake_dispatch(win, monkeypatch)

    win.data["temp_presets"][0] = "# t\nA final"
    win.sync_to_disk(force=True)
    snap_a = win._sync_pending
    gen_a = snap_a["gen"]

    _switch_profile(win, 2)
    assert win._sync_pending is None
    assert win._sync_pending_hold == {}
    assert worker.dispatch.calls[-1][0] is snap_a
    assert worker.dispatch.calls[-1][0]["gen"] == gen_a


def test_root_change_waits_for_old_physical_completion(win, monkeypatch, tmp_path):
    root_a = str(tmp_path / "root-a")
    root_b = str(tmp_path / "root-b")
    _setup(win, tmp_path, root=root_a)
    worker = _fake_dispatch(win, monkeypatch)

    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    snap_a, gen_a = worker.dispatch.calls[0]

    win.data["sync_path"] = root_b
    win.data["temp_presets"][0] = "# t\nroot B"
    win.sync_to_disk(force=True)
    snap_b = win._sync_pending

    assert win._sync_inflight_root == root_a
    win._sync_on_done(gen_a, snap_a, list(snap_a["files"]), [])
    assert win._sync_inflight_gen == snap_b["gen"]
    assert win._sync_inflight_root == root_b
    assert win._sync_written == {}

    win._sync_on_done(snap_b["gen"], snap_b, list(snap_b["files"]), [])
    assert win._sync_busy is False
    assert all(path.startswith(root_b) for path in win._sync_written)
