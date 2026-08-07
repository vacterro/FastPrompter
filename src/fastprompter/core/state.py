import copy
import json
import os
import re
import sqlite3
import threading
import time

from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.logging import logger
from fastprompter.utils.paths import get_db_path

# Settings whose value is a list or a dict and must therefore be written as
# JSON. Everything else goes through str(), and a dict written that way comes
# back with single quotes — not valid JSON, so it reloads as a raw string and
# the setting is silently lost. That is what happened to `silo_type_all`: a
# silo's Table/Kanban type never survived a restart.
#
# This lived inline in TWO places, and they had already drifted apart
# (`window_presets` was in one of them only), which is how a key gets missed.
# One tuple now, used by both.
_JSON_SETTINGS = (
    "cats_order", "custom_colors", "timers",
    "silo_last_edited", "silo_last_edited_all",
    "pinned_silos", "pinned_silos_all",
    "silo_ticked", "silo_ticked_all",
    "silo_children", "silo_children_all",
    "silo_collapsed", "silo_collapsed_all",
    "silo_colors", "silo_colors_all",
    "silo_folders", "silo_folders_all",
    "archive_silo_folders", "archive_silo_folders_all",
    "silo_project_paths", "silo_project_paths_all",
    "archive_project_paths", "archive_project_paths_all",
    "silo_gaps", "silo_gaps_all",
    "silo_view_state_all", "silo_type_all", "silo_session_all",
    # {event: {file, enabled, volume}} — a dict, so it MUST be here. Written
    # with str() it comes back single-quoted, json.loads rejects it, and the
    # whole sound panel silently forgets every choice on restart (the exact
    # way silo_type_all was lost, H-653).
    "sound_events", "saved_sound_mappings",
    # Same trap, three more keys that were written with str(): silo_types is
    # the per-category dict behind silo_type_all, saved_sound_mappings is what
    # the CS-style toggle restores from, watcher_skills_extra is a list of
    # dicts (a list survives str() only while its ELEMENTS do — dicts do not),
    # and custom_font_ids is a list of ints that survived on luck alone.
    "silo_types", "watcher_skills_extra", "custom_font_ids",
    "watcher_queues", "watcher_queues_all",
    "folder_trash_log", "hidden_categories", "window_presets",
)

# Never stored in the settings table: they have tables of their own.
_SETTINGS_SKIP = ("categories", "temp_presets_all", "archive_temp_presets_all",
                  "temp_presets", "archive_temp_presets")

# Every per-CATEGORY store. rename_category / del_category (main.py) move or
# delete the whole set in lockstep; a store left off this list keeps its data
# under the OLD project name after a rename, or leaves an orphan behind after
# a delete. Lives here (Qt-free) so the invariant test can assert it covers
# every live *_all key (T-758).
_PER_CATEGORY_STATE_KEYS = (
    "temp_presets_all", "archive_temp_presets_all",
    "pinned_silos_all", "silo_ticked_all", "silo_children_all",
    "silo_collapsed_all", "silo_colors_all", "silo_folders_all",
    "archive_silo_folders_all", "silo_last_edited_all",
    "silo_project_paths_all", "archive_project_paths_all",
    "watcher_queues_all", "silo_gaps_all",
    "silo_type_all", "silo_session_all", "silo_view_state_all",
)


def _encode_settings(data):
    """{key: text} for the settings table, JSON where the value needs it."""
    return {k: (json.dumps(v) if k in _JSON_SETTINGS else str(v))
            for k, v in data.items() if k not in _SETTINGS_SKIP}


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
            "ctrl_c_closes": "True", "hk_italic": "Ctrl+I", "hk_underline": "Ctrl+U", "theme": "Default", "ui_scale": "0.5", "button_scale": "1.0", "window_locked": "False", "silo_last_edited": {}, "pinned_silos": [], "silo_last_edited_all": {}, "pinned_silos_all": {}, "silo_ticked": [], "silo_ticked_all": {}, "silo_children": {}, "silo_children_all": {}, "silo_collapsed": [], "silo_collapsed_all": {}, "silo_gaps": [], "silo_gaps_all": {}, "hidden_categories": [], "silo_colors": {}, "silo_colors_all": {}, "silo_folders": {}, "silo_folders_all": {}, "archive_silo_folders": {}, "archive_silo_folders_all": {}, "silo_project_paths": {}, "silo_project_paths_all": {}, "silo_type_all": {}, "silo_session_all": {}, "archive_project_paths": {}, "archive_project_paths_all": {}, "folder_trash_log": [],
            "sidebar_right": "False", "sound_ui": "False", "sound_typewriter": "False", "sound_volume": "5", "portable_backup_enabled": "True", "language": "EN",
            "customize_toolbar": "False", "toolbar_order": "", "code_auto_gutter": "False"
        }
        # The shipped look (T-695): the baked profile wins over the bare
        # literals above, which stay as the last-resort skeleton. copy.deepcopy
        # because the values are mutable and a module-level dict handed out by
        # reference would let one profile's edits leak into the next
        # reset_data() — and into every test that touches them.
        self.data.update(copy.deepcopy(DEFAULT_PROFILE))

    def switch_profile(self, new_profile_id):
        if self.conn:
            self.save_data_to_db(self.data.get("last_text", ""), force=True)
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
                    src = sqlite3.connect(self.db_path)
                    dest = sqlite3.connect(self.db_path + ".bak")
                    try:
                        with dest:
                            src.backup(dest)
                    finally:
                        src.close()
                        dest.close()
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
                elif row[0] in ('silo_last_edited_all', 'pinned_silos_all', 'silo_ticked_all', 'silo_children', 'silo_children_all', 'silo_collapsed_all', 'silo_colors', 'silo_colors_all', 'silo_folders', 'silo_folders_all', 'archive_silo_folders', 'archive_silo_folders_all', 'silo_project_paths', 'silo_project_paths_all', 'archive_project_paths', 'archive_project_paths_all', 'folder_trash_log', 'silo_view_state_all', 'silo_type_all', 'silo_session_all', 'sound_events'):
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = {}
                elif row[0] in ('silo_gaps', 'silo_gaps_all', 'hidden_categories',
                                'silo_types', 'saved_sound_mappings',
                                'watcher_skills_extra', 'custom_font_ids'):
                    # silo_gaps is a LIST of slot indices, silo_gaps_all a
                    # dict of them per category. Both were missing from the
                    # save list below at first, so early builds wrote them
                    # with str(): a list survives that (valid JSON), a dict
                    # does not (single quotes), which silently emptied every
                    # saved gap on reload. ast recovers those older rows.
                    _empty = ({} if row[0] in ('silo_gaps_all', 'silo_types',
                                               'saved_sound_mappings') else [])
                    try:
                        self.data[row[0]] = json.loads(row[1])
                    except Exception:
                        try:
                            import ast
                            val = ast.literal_eval(row[1])
                            self.data[row[0]] = val if isinstance(val, type(_empty)) else _empty
                        except Exception as e:
                            logger.warning(f"Failed to parse {row[0]}: {e}")
                            self.data[row[0]] = _empty
                elif row[0] == 'timers':
                    # a LIST of timer dicts — falling back to {} would make
                    # load_timers see a mapping and silently drop them all
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = []
                elif row[0] in ('watcher_queues', 'watcher_queues_all'):
                    # Both are dicts. They were absent from the save list
                    # below for a while, so early builds wrote them as
                    # str(dict) — single-quoted, which json.loads rejects.
                    # ast.literal_eval recovers those; a real corruption
                    # still falls back to {} rather than crashing Alt+C.
                    try:
                        self.data[row[0]] = json.loads(row[1])
                    except Exception:
                        try:
                            import ast
                            val = ast.literal_eval(row[1])
                            self.data[row[0]] = val if isinstance(val, dict) else {}
                        except Exception as e:
                            logger.warning(f"Failed to parse {row[0]}: {e}")
                            self.data[row[0]] = {}
                elif row[0] == 'silo_last_edited':
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = {}
                elif row[0] in ('pinned_silos', 'silo_ticked', 'silo_collapsed', 'window_presets'):
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = []
                elif row[0] == 'custom_colors':
                    try:
                        self.data[row[0]] = json.loads(row[1])
                    except (json.JSONDecodeError, SyntaxError) as e:
                        logger.warning(f"Failed to parse custom_colors via json: {e}")
                        import ast
                        try:
                            self.data[row[0]] = ast.literal_eval(row[1])
                        except Exception as e2:
                            logger.warning(f"Failed to parse custom_colors using ast: {e2}")
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
            active_cat = self.data["cats_order"][min(self.data.get("last_tab_idx", 0), len(self.data["cats_order"])-1)] if self.data["cats_order"] else "Code"
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
        self._last_saved_settings = _encode_settings(self.data)

    def mark_dirty(self):
        self._db_dirty = True

    def _sanitize_cat_name(self, name: str) -> str:
        """Sanitize a category name for use as a directory name."""
        return re.sub(r'[^a-zA-Z0-9_ -]+', '', name).strip() or 'Unnamed'

    # _export_md_backup and its _safe_write helper lived here: a flat
    # ~/.fastprompter/ mirror of every snippet, silo and archive entry. It had
    # nine unit tests and NOT ONE production caller, which is worse than no
    # backup — it read like a safety net, in review and in the test list, while
    # writing nothing, ever. The dated per-project snapshots in
    # utils/portable_backup.py are the real thing and ARE wired into
    # save_data_to_db. `_sanitize_cat_name` above stays: backup_dialog borrows
    # it for the user-driven export. Removed 31.07.26 (T-633).

    def save_data_to_db(self, current_text, ui_settings=None, force=False):
        run_pb = False
        with self._lock:
            run_pb = self._save_data_to_db_locked(current_text, ui_settings, force)
            
        if run_pb:
            from fastprompter.utils.portable_backup import run_portable_backup
            run_portable_backup(self.data)

    def _save_data_to_db_locked(self, current_text, ui_settings=None, force=False):
        if not self.conn: return
        if not self._db_dirty and not force: return

        if ui_settings:
            self.data.update(ui_settings)

        self.data["last_text"] = current_text

        try:
            # Compute snapshots BEFORE tx; assign _last_saved_* AFTER tx commits
            current_settings = _encode_settings(self.data)
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
                            return True
            return False
        except sqlite3.Error:
            import traceback
            traceback.print_exc()
