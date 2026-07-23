import os

filepath = 'src/fastprompter/ui/saipen_dialog.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_font = """        font = QFont("Consolas" if os.name == "nt" else "Monospace", 10)
        self.text_state.setFont(font)
        self.text_board.setFont(font)
        self.text_log.setFont(font)"""

new_font = """        try:
            base_size = self.main_win._font_size
        except AttributeError:
            base_size = 11
            
        try:
            family = self.main_win._font_family
        except AttributeError:
            family = "Verdana"
            
        try:
            scale = self.main_win._ui_scale
        except AttributeError:
            scale = 1.0
            
        font_size = max(8, int(round(base_size * scale)))
        
        try:
            from fastprompter.utils.fonts import resolve_family, no_aa
            font = no_aa(QFont(resolve_family(family), font_size))
        except ImportError:
            font = QFont(family, font_size)
            
        self.text_state.setFont(font)
        self.text_board.setFont(font)
        self.text_log.setFont(font)"""

if old_font in text:
    text = text.replace(old_font, new_font)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched saipen_dialog font successfully.")
else:
    print("WARNING: Could not find old_font in saipen_dialog.py!")
