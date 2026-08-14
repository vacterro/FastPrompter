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
    assert win._sync_busy is False
    assert any("A newest" in text for text in win._sync_written.values())


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
