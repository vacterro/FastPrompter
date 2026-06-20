import os
import sqlite3
import json
from contextlib import contextmanager
from typing import Dict, List, Optional
from .models import Snippet, Category, Settings

DB_FILE = "data.db"

class StorageManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self.get_connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS snippets (id INTEGER PRIMARY KEY, cat TEXT, idx INTEGER, name TEXT, text TEXT, preset_idx INTEGER, font_size INTEGER)''')

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def load_settings(self) -> Settings:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            rows = cursor.fetchall()
            
            data = {}
            for row in rows:
                key, value = row[0], row[1]
                if key == 'cats_order':
                    try: data[key] = json.loads(value)
                    except json.JSONDecodeError: data[key] = ["Code", "Text", "Misc"]
                elif key in ('ui_scale', 'window_locked', 'sidebar_right'):
                    data[key] = value
                else:
                    try: data[key] = int(value)
                    except ValueError: data[key] = value

            # Map the parsed dict to Pydantic model
            return Settings(**data)

    def save_settings(self, settings: Settings):
        data = settings.model_dump()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for key, value in data.items():
                if key == 'cats_order':
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value_str))

    def load_snippets(self) -> Dict[str, List[Snippet]]:
        categories = {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, cat, name, text, preset_idx, font_size FROM snippets ORDER BY cat, idx")
            for row in cursor.fetchall():
                cat = row[1]
                if cat not in categories:
                    categories[cat] = []
                
                snippet = Snippet(
                    id=row[0],
                    name=row[2],
                    text=row[3],
                    preset_idx=row[4],
                    font_size=row[5]
                )
                categories[cat].append(snippet)
        return categories

    def save_snippets(self, categories: Dict[str, List[Snippet]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM snippets")
            for cat, snippets in categories.items():
                for idx, snippet in enumerate(snippets):
                    cursor.execute(
                        "INSERT INTO snippets (id, cat, idx, name, text, preset_idx, font_size) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (snippet.id, cat, idx, snippet.name, snippet.text, snippet.preset_idx, snippet.font_size)
                    )

    def backup(self):
        with self.get_connection() as src:
            with sqlite3.connect(self.db_path + ".bak") as dest:
                src.backup(dest)
