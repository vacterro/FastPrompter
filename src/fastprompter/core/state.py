import json
import os
import re
import sqlite3
import threading
import time

from fastprompter.core.logging import logger
from fastprompter.utils.paths import get_db_path
from fastprompter.utils.portable_backup import run_portable_backup


class FastPrompterState:
    def __init__(self, profile_id=1):
        self.profile_id = profile_id
        self._lock = threading.Lock()
        self.reset_data()
        self.db_path = get_db_path(self.profile_id)
        self.conn = None
        self._db_dirty = False
        self._last_saved_presets = set()
        self._last_saved_temp = {}
        self._last_saved_arc = {}
        self._last_saved_settings = {}
        self._last_backup_time = 0.0  # throttled backup
        self.init_db()

    def reset_data(self):
        self.data = {
            "categories": {"Code": [None]*100, "Text": [None]*100, "Misc": [None]*100},
            "cats_order": ["Code", "Text", "Misc"],
            "temp_presets_all": {"Code": [""]*10, "Text": [""]*10, "Misc": [""]*10},
            "archive_temp_presets_all": {"Code": [], "Text": [], "Misc": []},
            "last_text": "", "last_tab_idx": 0, "last_geometry": "", "active_temp_slot": 0,
            "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
            "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Alt+S", "always_on_top_hotkey": "Alt+E",
            "close_on_focus_loss": "True", "ctrl_c_closes": "True", "theme": "Default", "ui_scale": "1.0", "button_scale": "1.0", "window_locked": "False", "silo_last_edited": {}, "pinned_silos": [], "silo_last_edited_all": {}, "pinned_silos_all": {}, "silo_ticked": [], "silo_ticked_all": {},
            "sidebar_right": "False", "sound_ui": "False", "sound_typewriter": "False", "sound_volume": "5", "portable_backup_enabled": "True"
        }

    def switch_profile(self, new_profile_id):
        if self.conn:
            self.conn.close()
            self.conn = None
        self.profile_id = new_profile_id
        self.db_path = get_db_path(self.profile_id)
        self._db_dirty = False
        self.reset_data()
        self.init_db()

    def init_db(self):
        try:
            # Backup existing DB before connecting — prevents empty/new DB from destroying backup
            if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 24576:
                try:
                    with sqlite3.connect(self.db_path) as src:
                        with sqlite3.connect(self.db_path + ".bak") as dest:
                            src.backup(dest)
                except Exception:
                    import traceback
                    traceback.print_exc()

            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute('PRAGMA journal_mode=WAL;')
            self.conn.execute('PRAGMA synchronous=NORMAL;')
            cur = self.conn.cursor()

            cur.execute("CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
            cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")
            cur.execute("CREATE TABLE IF NOT EXISTS archive_temp_presets_v2 (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY (category, slot))")

            # Migration from global silos to Tab-based silos (defaulting to the first Tab)
            if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='temp_presets'").fetchone():
                cur.execute("INSERT OR IGNORE INTO temp_presets_v2 (category, slot, content) SELECT ?, slot, content FROM temp_presets", (self.data["cats_order"][0],))
                cur.execute("DROP TABLE temp_presets")

            if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='archive_temp_presets'").fetchone():
                cur.execute("INSERT OR IGNORE INTO archive_temp_presets_v2 (category, slot, content) SELECT ?, slot, content FROM archive_temp_presets", (self.data["cats_order"][0],))
                cur.execute("DROP TABLE archive_temp_presets")

            try: cur.execute("ALTER TABLE presets ADD COLUMN last_edited INTEGER")
            except Exception as e: logger.warning(f"Error migrating DB schema (ADD COLUMN): {e}")
            self.conn.commit()

            for row in cur.execute('SELECT key, value FROM settings'):
                if row[0] in ('last_tab_idx', 'active_temp_slot', 'font_size'):
                    try: self.data[row[0]] = int(row[1]) if row[1] else 0
                    except (ValueError, TypeError): self.data[row[0]] = 0
                elif row[0] == 'cats_order':
                    try:
                        parsed = json.loads(row[1])
                        self.data['cats_order'] = parsed if isinstance(parsed, list) else ["Code", "Text", "Misc"]
                    except json.JSONDecodeError: self.data['cats_order'] = ["Code", "Text", "Misc"]
                elif row[0] in ('ui_scale', 'window_locked', 'sidebar_right'): self.data[row[0]] = row[1]
                elif row[0] == 'hide_font': continue
                elif row[0] in ('silo_last_edited_all', 'pinned_silos_all', 'silo_ticked_all'):
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception: self.data[row[0]] = {}
                elif row[0] == 'silo_last_edited':
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception: self.data[row[0]] = {}
                elif row[0] in ('pinned_silos', 'silo_ticked'):
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception: self.data[row[0]] = []
                elif row[0] == 'custom_colors':
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception:
                        import ast
                        try: self.data[row[0]] = ast.literal_eval(row[1])
                        except Exception as e: logger.warning(f"Failed to parse custom_colors using ast: {e}")
                else: self.data[row[0]] = row[1]

            for cat in self.data['cats_order']:
                 if cat not in self.data['categories']: self.data['categories'][cat] = [None]*100

            for row in cur.execute('SELECT category, slot, name, content, last_edited FROM presets'):
                cat, slot, name, content, last_edited = row
                if cat in self.data["categories"] and 0 <= slot < 100:
                    self.data["categories"][cat][slot] = {"name": name, "text": content, "last_edited": last_edited or 0}

            temps = {cat: [""]*10 for cat in self.data["cats_order"]}
            for row in cur.execute('SELECT category, slot, content FROM temp_presets_v2 ORDER BY slot ASC'):
                cat, slot, content = row
                if cat not in temps: temps[cat] = [""]*10
                if not isinstance(slot, int): continue
                slot = min(max(slot, 0), 99)
                while len(temps[cat]) <= slot:
                    temps[cat].append("")
                temps[cat][slot] = content
            self.data["temp_presets_all"] = {k: v[:100] for k, v in temps.items()}

            arc_temps = {cat: [] for cat in self.data["cats_order"]}
            for row in cur.execute('SELECT category, slot, content FROM archive_temp_presets_v2 ORDER BY slot ASC'):
                cat, slot, content = row
                if cat not in arc_temps: arc_temps[cat] = []
                if not isinstance(slot, int): continue
                slot = min(max(slot, 0), 99)
                while len(arc_temps[cat]) <= slot:
                    arc_temps[cat].append("")
                arc_temps[cat][slot] = content
            self.data["archive_temp_presets_all"] = {k: [t for t in v if t.strip()] for k, v in arc_temps.items()}

            # Setup current tab proxies
            active_cat = self.data["cats_order"][self.data.get("last_tab_idx", 0)] if self.data["cats_order"] else "Code"
            if active_cat not in self.data["temp_presets_all"]: self.data["temp_presets_all"][active_cat] = [""]*10
            if active_cat not in self.data["archive_temp_presets_all"]: self.data["archive_temp_presets_all"][active_cat] = []
            self.data["temp_presets"] = self.data["temp_presets_all"][active_cat]
            self.data["archive_temp_presets"] = self.data["archive_temp_presets_all"][active_cat]

            if "active_temp_slot" not in self.data: self.data["active_temp_slot"] = 0

            self._db_dirty = False
            self._snapshot_state()
        except Exception:
            import traceback
            traceback.print_exc()

    def _snapshot_state(self):
        self._last_saved_presets = {(cat, i, item["name"], item["text"], item.get("last_edited", 0)) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item}
        self._last_saved_temp = {(cat, i, content) for cat, slots in self.data["temp_presets_all"].items() for i, content in enumerate(slots) if content}
        self._last_saved_arc = {(cat, i, content) for cat, slots in self.data["archive_temp_presets_all"].items() for i, content in enumerate(slots) if content}
        self._last_saved_settings = {k: (json.dumps(v) if k in ("cats_order", "custom_colors", "silo_last_edited", "pinned_silos", "silo_last_edited_all", "pinned_silos_all", "silo_ticked", "silo_ticked_all") else str(v)) for k, v in self.data.items() if k not in ("categories", "temp_presets_all", "archive_temp_presets_all", "temp_presets", "archive_temp_presets")}

    def mark_dirty(self):
        self._db_dirty = True

    def _sanitize_cat_name(self, name: str) -> str:
        """Sanitize a category name for use as a directory name."""
        import re
        return re.sub(r'[^a-zA-Z0-9_ -]+', '', name).strip() or 'Unnamed'

    def _safe_write(self, path: str, content: str) -> None:
        """Atomically write a file using temp + rename."""
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            import traceback
            traceback.print_exc()

    def _export_md_backup(self, snapshot: dict) -> None:
        """Export a snapshot of data as flat .md files under ~/.fastprompter/.

        Creates directories:
          Snippets/<Category>/  — one file per populated snippet slot
          Silos/<Category>/     — one file per non-empty silo
          Archive/<Category>/   — one file per non-empty archive entry
        """
        base = os.path.join(os.path.expanduser("~"), ".fastprompter")
        cats = snapshot.get("categories", {})
        temp_presets = snapshot.get("temp_presets_all", {})
        arc_presets = snapshot.get("archive_temp_presets_all", {})

        # Create skeleton directories upfront (even for empty snapshots)
        for cat_name in cats:
            safe_cat = self._sanitize_cat_name(cat_name)
            os.makedirs(os.path.join(base, "Snippets", safe_cat), exist_ok=True)
        for cat_name in temp_presets:
            safe_cat = self._sanitize_cat_name(cat_name)
            os.makedirs(os.path.join(base, "Silos", safe_cat), exist_ok=True)
        for cat_name in arc_presets:
            safe_cat = self._sanitize_cat_name(cat_name)
            os.makedirs(os.path.join(base, "Archive", safe_cat), exist_ok=True)

        # --- Snippets ---
        for cat_name, slots in cats.items():
            safe_cat = self._sanitize_cat_name(cat_name)
            cat_dir = os.path.join(base, "Snippets", safe_cat)
            for i, slot in enumerate(slots):
                if slot and isinstance(slot, dict) and slot.get("text", "").strip():
                    name = slot.get("name", f"Snippet {i+1}")
                    text = slot["text"]
                    fname = f"{i+1:03d}_{name}"[:80] + ".md"
                    fname = re.sub(r'[\\/:*?"<>|]+', '_', fname)
                    content = f"# {name}\n\n{text}\n"
                    self._safe_write(os.path.join(cat_dir, fname), content)

        # --- Silos ---
        for cat_name, presets in temp_presets.items():
            safe_cat = self._sanitize_cat_name(cat_name)
            silo_dir = os.path.join(base, "Silos", safe_cat)
            for i, text in enumerate(presets):
                if text and text.strip():
                    fname = f"silo_{i+1:03d}.md"
                    self._safe_write(os.path.join(silo_dir, fname), text)

        # --- Archive ---
        for cat_name, presets in arc_presets.items():
            safe_cat = self._sanitize_cat_name(cat_name)
            arc_dir = os.path.join(base, "Archive", safe_cat)
            for i, text in enumerate(presets):
                if text and text.strip():
                    fname = f"archive_{i+1:03d}.md"
                    self._safe_write(os.path.join(arc_dir, fname), text)

    def save_data_to_db(self, current_text, ui_settings=None, force=False):
        with self._lock:
            self._save_data_to_db_locked(current_text, ui_settings, force)

    def _save_data_to_db_locked(self, current_text, ui_settings=None, force=False):
        if not self.conn: return
        if not self._db_dirty and not force: return

        if ui_settings:
            self.data.update(ui_settings)

        self.data["last_text"] = current_text

        try:
            # Compute snapshots BEFORE tx; assign _last_saved_* AFTER tx commits
            current_settings = {k: (json.dumps(v) if k in ("cats_order", "custom_colors", "silo_last_edited", "pinned_silos", "silo_last_edited_all", "pinned_silos_all", "silo_ticked", "silo_ticked_all") else str(v)) for k, v in self.data.items() if k not in ("categories", "temp_presets_all", "archive_temp_presets_all", "temp_presets", "archive_temp_presets")}
            settings_to_save = [(k, v) for k, v in current_settings.items() if k not in self._last_saved_settings or self._last_saved_settings[k] != v]

            current_presets = {(cat, i, item["name"], item["text"], item.get("last_edited", 0)) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item}
            to_insert_presets = current_presets - self._last_saved_presets
            old_preset_keys = {(tup[0], tup[1]) for tup in self._last_saved_presets}
            new_preset_keys = {(tup[0], tup[1]) for tup in current_presets}
            to_delete_presets = old_preset_keys - new_preset_keys

            current_temp = {(cat, i, content) for cat, slots in self.data["temp_presets_all"].items() for i, content in enumerate(slots) if content}
            old_temp_keys = {(tup[0], tup[1]) for tup in self._last_saved_temp}
            new_temp_keys = {(tup[0], tup[1]) for tup in current_temp}
            temp_to_delete = old_temp_keys - new_temp_keys
            to_update_temp = current_temp - self._last_saved_temp

            current_arc = {(cat, i, content) for cat, slots in self.data["archive_temp_presets_all"].items() for i, content in enumerate(slots) if content}
            old_arc_keys = {(tup[0], tup[1]) for tup in self._last_saved_arc}
            new_arc_keys = {(tup[0], tup[1]) for tup in current_arc}
            arc_to_delete = old_arc_keys - new_arc_keys
            arc_to_update = current_arc - self._last_saved_arc

            with self.conn:
                cur = self.conn.cursor()
                if settings_to_save:
                    cur.executemany('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', settings_to_save)
                if to_delete_presets:
                    cur.executemany('DELETE FROM presets WHERE category=? AND slot=?', list(to_delete_presets))
                if to_insert_presets:
                    cur.executemany('INSERT OR REPLACE INTO presets (category, slot, name, content, last_edited) VALUES (?,?,?,?,?)', list(to_insert_presets))
                if temp_to_delete:
                    cur.executemany('DELETE FROM temp_presets_v2 WHERE category=? AND slot=?', list(temp_to_delete))
                if to_update_temp:
                    cur.executemany('INSERT OR REPLACE INTO temp_presets_v2 (category, slot, content) VALUES (?,?,?)', list(to_update_temp))
                if arc_to_delete:
                    cur.executemany('DELETE FROM archive_temp_presets_v2 WHERE category=? AND slot=?', list(arc_to_delete))
                if arc_to_update:
                    cur.executemany('INSERT OR REPLACE INTO archive_temp_presets_v2 (category, slot, content) VALUES (?,?,?)', list(arc_to_update))

            # Assign snapshots ONLY after tx commits successfully
            self._last_saved_settings = current_settings
            self._last_saved_presets = current_presets
            self._last_saved_temp = current_temp
            self._last_saved_arc = current_arc
            self._db_dirty = False

            # Backup throttled: max once per 60s to prevent I/O dominating saves
            if settings_to_save or to_insert_presets or to_delete_presets or to_update_temp or temp_to_delete or arc_to_update or arc_to_delete:
                now = time.time()
                if now - self._last_backup_time >= 60:
                    self._last_backup_time = now
                    dest_conn = None
                    try:
                        dest_conn = sqlite3.connect(self.db_path + ".bak")
                        with dest_conn:
                            self.conn.backup(dest_conn)
                    except Exception:
                        import traceback
                        traceback.print_exc()
                    finally:
                        if dest_conn:
                            try: dest_conn.close()
                            except Exception as e: logger.warning(f"Failed to close dest_conn in backup: {e}")
                        # Portable file backup (throttled internally)
                        if self.data.get("portable_backup_enabled", "True") == "True":
                            run_portable_backup(self.data)
        except sqlite3.Error:
            import traceback
            traceback.print_exc()
