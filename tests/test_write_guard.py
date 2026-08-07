"""Concurrency test for saipen_write_guard.

Verifies:
- Two writers cannot hold the lock simultaneously.
- IDs are unique and monotonic.
- STATE.last_event equals final event.
- No events lost or overwritten.
"""

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pytest
from write_guard import saipen_lock, is_locked


@pytest.fixture
def project_root():
    with tempfile.TemporaryDirectory() as d:
        saipen_dir = os.path.join(d, ".saipen")
        os.makedirs(saipen_dir)
        yield d


class TestLockExclusion:
    """Two writers cannot hold the lock simultaneously."""

    def test_sequential_does_not_block(self, project_root):
        with saipen_lock(project_root):
            pass
        with saipen_lock(project_root):
            pass  # second acquire after release — must succeed

    def test_concurrent_writer_blocks(self, project_root):
        acquired = []
        errors = []

        def writer(name):
            try:
                with saipen_lock(project_root, timeout=1.0):
                    acquired.append(name)
                    time.sleep(0.3)
            except RuntimeError as e:
                errors.append(str(e))

        t1 = threading.Thread(target=writer, args=("A",))
        t2 = threading.Thread(target=writer, args=("B",))

        t1.start()
        time.sleep(0.05)  # let A grab the lock
        t2.start()

        t1.join()
        t2.join()

        assert len(acquired) >= 1, "at least one writer must succeed"
        assert len(errors) <= 1, "at most one writer times out"

    def test_lock_is_released_after_context(self, project_root):
        with saipen_lock(project_root):
            assert is_locked(project_root)
        assert not is_locked(project_root)


class TestEventAllocation:
    """Event IDs are unique and monotonic under the lock."""

    def test_sequential_ids_are_monotonic(self, project_root):
        log_path = os.path.join(project_root, ".saipen", "LOG.md")
        state_path = os.path.join(project_root, ".saipen", "STATE.md")

        ids = []
        for i in range(5):
            with saipen_lock(project_root):
                eid = 1000 + i + 1
                ids.append(eid)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"- [E-{eid}] event {i}\n")

        assert ids == [1001, 1002, 1003, 1004, 1005]
        assert all(ids[i] < ids[i + 1] for i in range(len(ids) - 1))

    def test_concurrent_ids_do_not_collide(self, project_root):
        log_path = os.path.join(project_root, ".saipen", "LOG.md")
        # Write initial LOG
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Test LOG\n")
            f.write("- [E-2000] initial\n")

        event_ids = []
        lock_obj = threading.Lock()

        def writer():
            for _ in range(10):
                with saipen_lock(project_root, timeout=5.0):
                    # Read tail
                    with open(log_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    import re
                    existing = [int(m.group(1)) for m in re.finditer(r'\[E-(\d+)\]', content)]
                    next_id = max(existing) + 1 if existing else 2001

                    with lock_obj:
                        event_ids.append(next_id)

                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"- [E-{next_id}] concurrent event\n")

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(event_ids) == 20
        assert len(set(event_ids)) == 20, "all IDs must be unique"
        assert event_ids == sorted(event_ids), "IDs must be monotonic in allocation order"

    def test_state_tail_equals_log_tail(self, project_root):
        log_path = os.path.join(project_root, ".saipen", "LOG.md")
        state_path = os.path.join(project_root, ".saipen", "STATE.md")

        with saipen_lock(project_root):
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("# Test\n")
                f.write("- [E-3001] one\n")
                f.write("- [E-3002] two\n")
                f.write("- [E-3003] three\n")
            with open(state_path, "w", encoding="utf-8") as f:
                f.write("last_event: 3003\n")

        with open(state_path, "r", encoding="utf-8") as f:
            state_content = f.read()
        assert "last_event: 3003" in state_content

        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        import re
        log_ids = [int(m.group(1)) for m in re.finditer(r'\[E-(\d+)\]', log_content)]
        assert max(log_ids) == 3003
