import sqlite3
import json
from fastprompter.utils.paths import get_db_path

class FastPrompterState:
    def __init__(self):
        self.data = {
            "categories": {"Code": [None]*100, "Text": [None]*100, "Misc": [None]*100}, 
            "cats_order": ["Code", "Text", "Misc"],
            "last_text": "", "last_tab_idx": 0, "last_geometry": "", "temp_presets": [""]*10, "archive_temp_presets": [""]*100, "active_temp_slot": 0,
            "font_size": 11, "preview_mode": "None", "paste_mode": "Plain", "tray_visible": "True", "global_hotkey": "Alt+X",
            "pie_menu_hotkey": "Shift+Alt+X", "lock_window_hotkey": "Ctrl+Shift+L", "always_on_top_hotkey": "Ctrl+Shift+E",
            "close_on_focus_loss": "True", "ctrl_c_closes": "True", "theme": "Default", "ui_scale": "1.0", "button_scale": "1.0", "window_locked": "False",
            "sidebar_right": "False"
        }
        self.db_path = get_db_path()
        self.conn = None
        self._db_dirty = False
        
        self.init_db()

    def init_db(self):
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute('PRAGMA journal_mode=WAL;')
            cur = self.conn.cursor()
            try:
                with sqlite3.connect(self.db_path + ".bak") as dest:
                    self.conn.backup(dest)
            except Exception: pass
            
            cur.execute("CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, name TEXT, content TEXT, PRIMARY KEY (category, slot))")
            cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS temp_presets (slot INTEGER PRIMARY KEY, content TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS archive_temp_presets (slot INTEGER PRIMARY KEY, content TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS undo_history (id INTEGER PRIMARY KEY AUTOINCREMENT, delta TEXT)")
            self.conn.commit()

            for row in cur.execute('SELECT key, value FROM settings'):
                if row[0] in ('last_tab_idx', 'active_temp_slot', 'font_size'): self.data[row[0]] = int(row[1])
                elif row[0] == 'cats_order':
                    try: self.data['cats_order'] = json.loads(row[1])
                    except json.JSONDecodeError: self.data['cats_order'] = ["Code", "Text", "Misc"]
                elif row[0] in ('ui_scale', 'window_locked', 'sidebar_right'): self.data[row[0]] = row[1]
                elif row[0] == 'hide_font': continue
                elif row[0] == 'custom_colors':
                    try: self.data[row[0]] = json.loads(row[1])
                    except Exception:
                        import ast
                        try: self.data[row[0]] = ast.literal_eval(row[1])
                        except Exception: pass
                else: self.data[row[0]] = row[1]
                    
            for cat in self.data['cats_order']:
                 if cat not in self.data['categories']: self.data['categories'][cat] = [None]*100
            if "__Archive__" not in self.data["categories"]:
                 self.data["categories"]["__Archive__"] = [None]*100
                    
            for row in cur.execute('SELECT category, slot, name, content FROM presets'):
                cat, slot, name, content = row
                if cat in self.data["categories"] and 0 <= slot < 100: self.data["categories"][cat][slot] = {"name": name, "text": content}
                    
            temps, max_slot = [""]*10, 9
            for row in cur.execute('SELECT slot, content FROM temp_presets ORDER BY slot ASC'):
                slot, content = row
                if slot > max_slot: temps.extend([""] * (slot - max_slot)); max_slot = slot
                if 0 <= slot < 100: temps[slot] = content
            self.data["temp_presets"] = temps[:100]
            
            arc_temps, arc_max_slot = [""]*100, 99
            for row in cur.execute('SELECT slot, content FROM archive_temp_presets ORDER BY slot ASC'):
                slot, content = row
                if 0 <= slot < 100: arc_temps[slot] = content
            self.data["archive_temp_presets"] = arc_temps[:100]

            if "active_temp_slot" not in self.data: self.data["active_temp_slot"] = 0
            
            self._db_dirty = False
        except Exception: pass

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
                settings_to_save = []
                for k, v in self.data.items():
                    if k in ("categories", "temp_presets", "archive_temp_presets"): continue
                    if k == "cats_order":
                        settings_to_save.append((k, json.dumps(v)))
                    elif k == "custom_colors":
                        settings_to_save.append((k, json.dumps(v)))
                    else:
                        settings_to_save.append((k, str(v)))
                        
                cur.executemany('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', settings_to_save)

                cur.execute('DELETE FROM presets')
                presets_to_save = [(cat, i, item["name"], item["text"]) for cat, slots in self.data["categories"].items() for i, item in enumerate(slots) if item]
                cur.executemany('INSERT INTO presets (category, slot, name, content) VALUES (?,?,?,?)', presets_to_save)

                cur.execute('DELETE FROM temp_presets')
                cur.executemany('INSERT INTO temp_presets (slot, content) VALUES (?,?)', [(i, content) for i, content in enumerate(self.data["temp_presets"])])

                cur.execute('DELETE FROM archive_temp_presets')
                cur.executemany('INSERT INTO archive_temp_presets (slot, content) VALUES (?,?)', [(i, content) for i, content in enumerate(self.data["archive_temp_presets"]) if content])
            self._db_dirty = False
            try:
                dest_conn = sqlite3.connect(self.db_path + ".bak")
                with dest_conn:
                    self.conn.backup(dest_conn)
                dest_conn.close()
            except Exception: pass
        except sqlite3.Error: pass

    def push_undo(self, delta_json):
        if not self.conn: return
        try:
            with self.conn:
                self.conn.execute("INSERT INTO undo_history (delta) VALUES (?)", (delta_json,))
                self.conn.execute("DELETE FROM undo_history WHERE id NOT IN (SELECT id FROM undo_history ORDER BY id DESC LIMIT 50)")
        except sqlite3.Error: pass

    def pop_undo(self):
        if not self.conn: return None
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT id, delta FROM undo_history ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                with self.conn:
                    self.conn.execute("DELETE FROM undo_history WHERE id = ?", (row[0],))
                return row[1]
        except sqlite3.Error: pass
        return None
