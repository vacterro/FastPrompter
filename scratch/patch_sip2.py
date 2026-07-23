import os
import re

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_func = """    def open_saipen_dialog(self, tab):
        from fastprompter.ui.saipen_dialog import SaipenViewerDialog
        import sip
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        folder = paths.get("folder", "")
        if folder:
            import os
            saipen_dir = os.path.join(folder, ".saipen")
            if os.path.isdir(saipen_dir):
                if hasattr(self, "_saipen_dialog") and getattr(self, "_saipen_dialog", None) is not None and not sip.isdeleted(self._saipen_dialog) and self._saipen_dialog.isVisible():
                    self._saipen_dialog.raise_()
                    self._saipen_dialog.activateWindow()
                    for i in range(self._saipen_dialog.tabs.count()):
                        if self._saipen_dialog.tabs.tabText(i) == tab:
                            self._saipen_dialog.tabs.setCurrentIndex(i)
                            break
                else:
                    self._saipen_dialog = SaipenViewerDialog(self, saipen_dir, tab)
                    self._saipen_dialog.show()"""

new_func = """    def open_saipen_dialog(self, tab):
        from fastprompter.ui.saipen_dialog import SaipenViewerDialog
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        folder = paths.get("folder", "")
        if folder:
            import os
            saipen_dir = os.path.join(folder, ".saipen")
            if os.path.isdir(saipen_dir):
                is_open = False
                if hasattr(self, "_saipen_dialog") and getattr(self, "_saipen_dialog", None) is not None:
                    try:
                        is_open = self._saipen_dialog.isVisible()
                    except RuntimeError:
                        pass
                
                if is_open:
                    self._saipen_dialog.raise_()
                    self._saipen_dialog.activateWindow()
                    for i in range(self._saipen_dialog.tabs.count()):
                        if self._saipen_dialog.tabs.tabText(i) == tab:
                            self._saipen_dialog.tabs.setCurrentIndex(i)
                            break
                else:
                    self._saipen_dialog = SaipenViewerDialog(self, saipen_dir, tab)
                    self._saipen_dialog.show()"""

if old_func in text:
    text = text.replace(old_func, new_func)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched open_saipen_dialog successfully.")
else:
    print("WARNING: Could not find old_func in main.py!")
