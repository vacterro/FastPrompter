import time
import pytest
import sqlite3
import os
import sys

# Ensure src is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from fastprompter.core.state import FastPrompterState

@pytest.fixture(scope="function")
def db_state(tmp_path):
    """Fixture that provides an isolated DB state for testing."""
    os.environ["FASTPROMPTER_TEST_DB"] = str(tmp_path / "test_db.sqlite")
    
    # We monkeypatch get_db_path indirectly by just setting the state path after init
    state = FastPrompterState(profile_id=999)
    # Re-route db
    if state.conn:
        state.conn.close()
    state.db_path = str(tmp_path / "test_db.sqlite")
    state.init_db()
    
    # Pre-populate with 300 snippets (100 per category)
    for cat in state.data["categories"]:
        state.data["categories"][cat] = [{"name": f"Snippet {i}", "text": f"Content {i}"} for i in range(100)]
    
    yield state
    
    if state.conn:
        state.conn.close()

def test_save_performance_delta(db_state):
    """Test that delta updates are significantly faster than full rewrites."""
    # First save (inserts everything)
    db_state.mark_dirty()
    start_time = time.perf_counter()
    db_state.save_data_to_db("init", force=True)
    first_save_time = time.perf_counter() - start_time
    
    # Second save (settings-only change: last_text updated)
    db_state.mark_dirty()
    start_time = time.perf_counter()
    db_state.save_data_to_db("init_again", force=True)
    second_save_time = time.perf_counter() - start_time
    
    # Third save (one change)
    db_state.data["categories"]["Code"][0] = {"name": "Changed", "text": "Modified"}
    db_state.mark_dirty()
    start_time = time.perf_counter()
    db_state.save_data_to_db("changed", force=True)
    third_save_time = time.perf_counter() - start_time

    print(f"\n[Performance] Full Insert: {first_save_time:.5f}s")
    print(f"[Performance] No-Op Delta: {second_save_time:.5f}s")
    print(f"[Performance] Single Edit Delta: {third_save_time:.5f}s")
    
    # Delta should be at least marginally faster than full insert
    assert second_save_time < first_save_time * 0.99, "Delta update (settings-only change) should be faster than full insert"
    assert third_save_time < first_save_time * 0.99, "Delta update (single edit) should be faster than full insert"
