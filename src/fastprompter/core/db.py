import os
import sqlite3
import json
import logging
import time
from fastprompter.core.utils import safe_set_clipboard

logger = logging.getLogger(__name__)

DB_FILE = "C:/Users/vac34/.gemini/antigravity/__FastPrompter__.db"

def init_db(data_ref, callback=None):
    """
    Initializes the SQLite database and loads data into `data_ref`.
    """
    try:
        conn = sqlite3.connect(DB_FILE, check_same_thread=True)
        # WAL mode is used but with safe backups
        conn.execute('PRAGMA journal_mode=WAL;')
        
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS presets (category TEXT, slot INTEGER, content TEXT, PRIMARY KEY(category, slot))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS temp_presets (slot INTEGER PRIMARY KEY, content TEXT)''')
        
        # Load settings
        cur.execute('SELECT key, value FROM settings')
        for k, v in cur.fetchall():
            # handle booleans and strings explicitly
            data_ref[k] = v
            
        # Defaults if missing
        for key, default in [
            ("always_on_top", "True"), ("opacity", "100"), ("theme", "dark"),
            ("x", "100"), ("y", "100"), ("width", "960"), ("height", "540"),
            ("locked", "False"), ("font_family", "Consolas"), ("font_size", "11"),
            ("format_mode", "0"), ("hk_summon", "Alt+Shift+Q"), ("hk_hide", "Ctrl+Alt+Shift+Q"),
            ("hk_quick_list", "Ctrl+`"), ("categories", json.dumps(["Default"])),
            ("act_as_normal_window", "False"), ("hide_shortkeys", "False"),
            ("lock_to_cursor", "False")
        ]:
            if key not in data_ref:
                data_ref[key] = default

        # Parse categories
        try:
            cats = json.loads(data_ref["categories"])
            if not isinstance(cats, list) or not cats:
                cats = ["Default"]
        except Exception:
            cats = ["Default"]
            
        data_ref["categories_list"] = cats
        data_ref["categories"] = {}
        
        for c in cats:
            data_ref["categories"][c] = [None] * 100
            cur.execute('SELECT slot, content FROM presets WHERE category=?', (c,))
            for slot, content in cur.fetchall():
                if 0 <= slot < 100:
                    data_ref["categories"][c][slot] = content
                    
        # Load silos
        data_ref["temp_presets"] = [""] * 10
        cur.execute('SELECT slot, content FROM temp_presets')
        for slot, content in cur.fetchall():
            if 0 <= slot < 10:
                data_ref["temp_presets"][slot] = content
                
        if callback:
            callback(conn)
        return conn
    except Exception as e:
        logger.error(f"Failed to init DB: {e}")
        return None

def save_data_to_db(conn, data_ref):
    """
    Saves data to DB and performs a native SQLite backup to .bak.
    """
    if not conn: return
    try:
        with conn:
            cur = conn.cursor()
            settings = [
                ('always_on_top', str(data_ref.get("always_on_top", "True"))),
                ('opacity', str(data_ref.get("opacity", 100))),
                ('theme', str(data_ref.get("theme", "dark"))),
                ('x', str(data_ref.get("x", 100))),
                ('y', str(data_ref.get("y", 100))),
                ('width', str(data_ref.get("width", 960))),
                ('height', str(data_ref.get("height", 540))),
                ('locked', str(data_ref.get("locked", "False"))),
                ('lock_to_cursor', str(data_ref.get("lock_to_cursor", "False"))),
                ('font_family', str(data_ref.get("font_family", "Consolas"))),
                ('font_size', str(data_ref.get("font_size", 11))),
                ('format_mode', str(data_ref.get("format_mode", 0))),
                ('hk_summon', str(data_ref.get("hk_summon", "Alt+Shift+Q"))),
                ('hk_hide', str(data_ref.get("hk_hide", "Ctrl+Alt+Shift+Q"))),
                ('hk_quick_list', str(data_ref.get("hk_quick_list", "Ctrl+`"))),
                ('categories', json.dumps(data_ref.get("categories_list", ["Default"]))),
                ('act_as_normal_window', str(data_ref.get("act_as_normal_window", "False"))),
                ('hide_shortkeys', str(data_ref.get("hide_shortkeys", "False")))
            ]
            cur.executemany('REPLACE INTO settings (key, value) VALUES (?,?)', settings)
            
            cur.execute('DELETE FROM presets')
            presets_data = []
            for c, slots in data_ref["categories"].items():
                for i, content in enumerate(slots):
                    if content is not None:
                        presets_data.append((c, i, content))
            if presets_data:
                cur.executemany('INSERT INTO presets (category, slot, content) VALUES (?,?,?)', presets_data)
                
            cur.execute('DELETE FROM temp_presets')
            cur.executemany('INSERT INTO temp_presets (slot, content) VALUES (?,?)', 
                            [(i, content) for i, content in enumerate(data_ref.get("temp_presets", [""]*10))])
            
        # Native backup safely avoiding WAL read-locking issues
        try:
            dest_conn = sqlite3.connect(DB_FILE + ".bak")
            with dest_conn:
                conn.backup(dest_conn)
            dest_conn.close()
        except Exception as e:
            logger.warning(f"Backup failed: {e}")
            
    except sqlite3.Error as e:
        logger.error(f"SQLite error during save: {e}")
