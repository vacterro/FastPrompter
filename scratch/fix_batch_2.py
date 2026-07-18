import os
import re

PROJECT = r"v:\___VAC\__K\__CODE\_PY\_FastPrompter"

def fix_main_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "main.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # T-164: _save_undo_state thread race
    old_save_undo = """    def _save_undo_state(self):
        import json
        import os
        import threading
        def save():
            try:
                db_path = getattr(self.state, "db_path", "")
                if not db_path:
                    return
                undo_path = os.path.splitext(db_path)[0] + "_undo.json"
                with open(undo_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "undo": getattr(self, "data_undo_stack", []),
                        "redo": getattr(self, "data_redo_stack", [])
                    }, f)
            except Exception as e:
                from fastprompter.core.logging import logger
                logger.error(f"Failed to save undo state: {e}")
        threading.Thread(target=save, daemon=True).start()"""
        
    new_save_undo = """    def _save_undo_state(self):
        import json
        import os
        import threading
        u_copy = list(getattr(self, "data_undo_stack", []))
        r_copy = list(getattr(self, "data_redo_stack", []))
        def save(undo_data, redo_data):
            try:
                db_path = getattr(self.state, "db_path", "")
                if not db_path:
                    return
                undo_path = os.path.splitext(db_path)[0] + "_undo.json"
                with open(undo_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "undo": undo_data,
                        "redo": redo_data
                    }, f)
            except Exception as e:
                from fastprompter.core.logging import logger
                logger.error(f"Failed to save undo state: {e}")
        threading.Thread(target=save, args=(u_copy, r_copy), daemon=True).start()"""
    if old_save_undo in content:
        content = content.replace(old_save_undo, new_save_undo)
        print("T-164 fixed.")

    # T-167: _update_visible_silo_count
    old_silo_count = """    def _update_visible_silo_count(self):
        if hasattr(self, "silos_widget") and self.silos_widget.height() > 0:
            # Estimate button height from the first visible button, fallback to 24*scale
            estimate = 24
            for btn in getattr(self, "silo_buttons", []):
                if btn.isVisible():
                    bh = btn.height()
                    if bh > 0:
                        estimate = bh
                    break"""
    new_silo_count = """    def _update_visible_silo_count(self):
        if hasattr(self, "silos_widget") and self.silos_widget.height() > 0:
            estimate = int(24 * getattr(self, "_ui_scale", 1.0))
            for btn in getattr(self, "silo_buttons", []):
                bh = btn.height() if btn.isVisible() else btn.sizeHint().height()
                if bh > 0:
                    estimate = bh
                    break"""
    if old_silo_count in content:
        content = content.replace(old_silo_count, new_silo_count)
        print("T-167 fixed.")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def fix_state_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "core", "state.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # T-165: state.py backup connection leak
    old_backup = """                    with sqlite3.connect(self.db_path) as src:
                        with sqlite3.connect(self.db_path + ".bak") as dest:
                            src.backup(dest)"""
    new_backup = """                    src = sqlite3.connect(self.db_path)
                    dest = sqlite3.connect(self.db_path + ".bak")
                    try:
                        with dest:
                            src.backup(dest)
                    finally:
                        src.close()
                        dest.close()"""
    if old_backup in content:
        content = content.replace(old_backup, new_backup)
        print("T-165 fixed (line 56).")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def fix_file_container_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "ui", "file_container.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # T-171: _thumb_cache unbounded
    old_cache = "                    self._thumb_cache[path] = (mtime, icon)"
    new_cache = "                    if len(self._thumb_cache) > 200: self._thumb_cache.clear()\n                    self._thumb_cache[path] = (mtime, icon)"
    if old_cache in content:
        content = content.replace(old_cache, new_cache)
        print("T-171 fixed.")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

fix_main_py()
fix_state_py()
fix_file_container_py()

