import os
import re

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_func = """    def _update_project_buttons(self):
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        
        has_folder = bool(paths.get("folder"))
        has_exe = bool(paths.get("executable"))
        
        if hasattr(self, "btn_project_folder"):
            self.btn_project_folder.setVisible(has_folder)
        if hasattr(self, "btn_project_run"):
            self.btn_project_run.setVisible(has_exe)"""

new_func = """    def _update_project_buttons(self):
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        
        has_folder = bool(paths.get("folder"))
        has_exe = bool(paths.get("executable"))
        
        if hasattr(self, "btn_project_folder"):
            self.btn_project_folder.setVisible(has_folder)
        if hasattr(self, "btn_project_run"):
            self.btn_project_run.setVisible(has_exe)

        has_saipen = False
        if has_folder:
            import os
            saipen_dir = os.path.join(paths["folder"], ".saipen")
            if os.path.isdir(saipen_dir):
                has_saipen = True
                
        if hasattr(self, "btn_saipen_state"):
            self.btn_saipen_state.setVisible(has_saipen)
        if hasattr(self, "btn_saipen_board"):
            self.btn_saipen_board.setVisible(has_saipen)
        if hasattr(self, "btn_saipen_log"):
            self.btn_saipen_log.setVisible(has_saipen)"""

if old_func in text:
    text = text.replace(old_func, new_func)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched _update_project_buttons successfully.")
else:
    print("WARNING: Could not find old_func in main.py!")
