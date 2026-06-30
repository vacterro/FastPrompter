import sqlite3
import json
import time
from fastprompter.utils.paths import get_db_path

class FastPrompterState:
    def __init__(self, profile_id=1):
        self.profile_id = profile_id
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
            "last_text": "", "last_tab_idx": 0, "last_geometry": "", "temp_presets": [""]*10, "archive_temp_presets": [], "active_temp_slot": 0,
            "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
            "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Ctrl+Shift+L", "always_on_top_hotkey": "Ctrl+Shift+E",
            "close_on_focus_loss": "True", "ctrl_c_closes": "True", "theme": "Default", "ui_scale": "1.0", "button_scale": "1.0", "window_locked": "False", "silo_last_edited": "{}",
            "sidebar_right": "False", "sound_ui": "False", "sound_typewriter": "False", "sound_volume": "5"
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
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute('PRAGMA journal_mode=WAL;')
            self.conn.execute('PRAGMA synchronous=NORMAL;')
            cur = self.conn.cursor()
            try:
                with sqlite3.connect(self.db_path + ".bak") as dest:
                    self.conn.backup(dest)
            except Exception: pass
            
            cur.execute("CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
            cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS temp_presets (slot INTEGER PRIMARY KEY, content TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS archive_temp_presets (slot INTEGER PRIMARY KEY, content TEXT)")
            try: cur.execute("ALTER TABLE presets ADD COLUMN last_edited INTEGER")
            except Exception: pass
            self.conn.commit()

            for row in cur.execute('SELECT key, value FROM settings'):
                if row[0] in ('last_tab_idx', 'active_temp_slot', 'font_size'): self.data[row[0]] = int(row[1])
                elif row[0] == 'cats_order':
                    try:
                        parsed = json.loads(row[1])
                        self.data['cats_order'] = parsed if isinstance(parsed, list) else ["Code", "Text", "Misc"]
                    except json.JSONDecodeError: self.data['cats_order'] = ["Code", "Text", "Misc"]
                elif row[0] in ('ui_scale', 'window_locked', 'sidebar_right'): self.data[row[0]] = row[1]
                elif row[0] == 'hide_font': continue
                elif row[0] == 'silo_last_edited':
                    try: self.data[row[0]] = json.loads(row[1])
                    except: self.data[row[0]] = {}
                elif row[0] == 'custom_colors':
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception:
                        import ast
                        try: self.data[row[0]] = ast.literal_eval(row[1])
                        except Exception: pass
                else: self.data[row[0]] = row[1]
                    
            for cat in self.data['cats_order']:
                 if cat not in self.data['categories']: self.data['categories'][cat] = [None]*100
                    
            for row in cur.execute('SELECT category, slot, name, content, last_edited FROM presets'):
                cat, slot, name, content, last_edited = row
                if cat in self.data["categories"] and 0 <= slot < 100:
                    self.data["categories"][cat][slot] = {"name": name, "text": content, "last_edited": last_edited or 0}
                    
            temps = []
            for row in cur.execute('SELECT slot, content FROM temp_presets ORDER BY slot ASC'):
                slot, content = row
                while len(temps) <= slot:
                    temps.append("")
                if 0 <= slot < 100: temps[slot] = content
                
            if not temps:
                temps = [""] * 10
                
            self.data["temp_presets"] = temps[:100]
            
            arc_temps = []
            for row in cur.execute('SELECT slot, content FROM archive_temp_presets ORDER BY slot ASC'):
                slot, content = row
                while len(arc_temps) <= slot:
                    arc_temps.append("")
                arc_temps[slot] = content
            self.data["archive_temp_presets"] = [t for t in arc_temps if t.strip()]

            if "active_temp_slot" not in self.data: self.data["active_temp_slot"] = 0
            
            self._db_dirty = False
            self._snapshot_state()
        except Exception: pass

    def _snapshot_state(self):
        self._last_saved_presets = {(cat, i, item["name"], item["text"], item.get("last_edited", 0)) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item}
        self._last_saved_temp = {i: content for i, content in enumerate(self.data["temp_presets"])}
        self._last_saved_arc = {i: content for i, content in enumerate(self.data["archive_temp_presets"]) if content}
        self._last_saved_settings = {k: (json.dumps(v) if k in ("cats_order", "custom_colors", "silo_last_edited") else str(v)) for k, v in self.data.items() if k not in ("categories", "temp_presets", "archive_temp_presets")}

    def mark_dirty(self):
        self._db_dirty = True

    def save_data_to_db(self, current_text, ui_settings=None, force=False):
        if not self.conn: return
        if not self._db_dirty and not force: return

        if ui_settings:
            self.data.update(ui_settings)
            
        self.data["last_text"] = current_text

        try:
            with self.conn:
                cur = self.conn.cursor()
                
                # Settings delta
                current_settings = {k: (json.dumps(v) if k in ("cats_order", "custom_colors", "silo_last_edited") else str(v)) for k, v in self.data.items() if k not in ("categories", "temp_presets", "archive_temp_presets")}
                settings_to_save = [(k, v) for k, v in current_settings.items() if k not in self._last_saved_settings or self._last_saved_settings[k] != v]
                if settings_to_save:
                    cur.executemany('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', settings_to_save)
                self._last_saved_settings = current_settings
                
                # Presets delta
                current_presets = {(cat, i, item["name"], item["text"], item.get("last_edited", 0)) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item}
                to_insert_presets = current_presets - self._last_saved_presets
                old_preset_keys = {(tup[0], tup[1]) for tup in self._last_saved_presets}
                new_preset_keys = {(tup[0], tup[1]) for tup in current_presets}
                to_delete_presets = old_preset_keys - new_preset_keys
                
                if to_delete_presets:
                    cur.executemany('DELETE FROM presets WHERE category=? AND slot=?', list(to_delete_presets))
                if to_insert_presets:
                    cur.executemany('INSERT OR REPLACE INTO presets (category, slot, name, content, last_edited) VALUES (?,?,?,?,?)', list(to_insert_presets))
                self._last_saved_presets = current_presets
                
                # Temp presets delta
                current_temp = {i: content for i, content in enumerate(self.data["temp_presets"])}
                
                temp_to_delete = set(self._last_saved_temp.keys()) - set(current_temp.keys())
                if temp_to_delete:
                    cur.executemany('DELETE FROM temp_presets WHERE slot=?', [(i,) for i in temp_to_delete])
                    
                to_update_temp = [(i, content) for i, content in current_temp.items() if self._last_saved_temp.get(i) != content]
                if to_update_temp:
                    cur.executemany('INSERT OR REPLACE INTO temp_presets (slot, content) VALUES (?,?)', to_update_temp)
                self._last_saved_temp = current_temp
                
                # Archive presets delta
                current_arc = {i: content for i, content in enumerate(self.data["archive_temp_presets"]) if content}
                old_arc_keys = set(self._last_saved_arc.keys())
                new_arc_keys = set(current_arc.keys())
                arc_to_delete = old_arc_keys - new_arc_keys
                
                if arc_to_delete:
                    cur.executemany('DELETE FROM archive_temp_presets WHERE slot=?', [(i,) for i in arc_to_delete])
                arc_to_update = [(i, content) for i, content in current_arc.items() if self._last_saved_arc.get(i) != content]
                if arc_to_update:
                    cur.executemany('INSERT OR REPLACE INTO archive_temp_presets (slot, content) VALUES (?,?)', arc_to_update)
                self._last_saved_arc = current_arc
                
            self._db_dirty = False
            # Backup throttled: max once per 60s to prevent I/O dominating saves
            if settings_to_save or to_insert_presets or to_delete_presets or to_update_temp or temp_to_delete or arc_to_update or arc_to_delete:
                now = time.time()
                if now - self._last_backup_time >= 60:
                    self._last_backup_time = now
                    try:
                        dest_conn = sqlite3.connect(self.db_path + ".bak")
                        with dest_conn:
                            self.conn.backup(dest_conn)
                        dest_conn.close()
                    except Exception: pass
        except sqlite3.Error: pass
