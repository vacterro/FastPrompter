import os

PROJECT = r"v:\___VAC\__K\__CODE\_PY\_FastPrompter"

def fix_main_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "main.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # T-179: open_file_container imports
    if "from fastprompter.ui.file_container import FileContainerPanel" in content[content.find("def open_file_container"):]:
        content = content.replace("    def open_file_container", "from fastprompter.ui.file_container import FileContainerPanel\n    def open_file_container")
        old_import = "        from fastprompter.ui.file_container import FileContainerPanel\n"
        content = content.replace(old_import, "", 1)
        print("T-179 fixed.")

    # T-193: _update_files_button imports
    if "from fastprompter.ui.file_container import folder_summary, silo_file_count" in content[content.find("def _update_files_button"):]:
        content = content.replace("from fastprompter.ui.file_container import FileContainerPanel\n", "from fastprompter.ui.file_container import FileContainerPanel, folder_summary, silo_file_count\n")
        old_import2 = "        from fastprompter.ui.file_container import folder_summary, silo_file_count\n"
        content = content.replace(old_import2, "", 1)
        print("T-193 fixed.")

    # T-192: _live_folder_sync reads toPlainText twice
    old_sync = """        first_nl = self.text_area.toPlainText()
        first = first_nl[:first_nl.index("\\n")] if "\\n" in first_nl else first_nl"""
    new_sync = """        doc = self.text_area.document()
        first = doc.firstBlock().text() if doc.blockCount() > 0 else \"\""""
    if old_sync in content:
        content = content.replace(old_sync, new_sync)
        print("T-192 fixed.")

    # T-194: change_profile hardcodes "Text" as default tab
    old_tab = """        for i, cat in enumerate(self.data["cats_order"]):
            if cat == "Text":
                target_idx = i
                break"""
    new_tab = """        for i, cat in enumerate(self.data["cats_order"]):
            if cat in ("Text", self.data["cats_order"][0]):
                target_idx = i
                break"""
    if old_tab in content:
        content = content.replace(old_tab, new_tab)
        print("T-194 fixed.")

    # T-189: change_profile doesn't clear text_area undo history
    if "self.build_categories()" in content[content.find("def change_profile"):]:
        old_cp = """        self.build_categories()
        self.apply_theme()"""
        new_cp = """        self.build_categories()
        self.text_area.document().clearUndoRedoStacks()
        self.apply_theme()"""
        if old_cp in content:
            content = content.replace(old_cp, new_cp)
            print("T-189 fixed.")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def fix_snippet_panel_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "ui", "snippet_panel.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # T-175: snippet_panel.py _hover_timer runs continuously
    # Check if we can stop it when mouse leaves or only start when entering.
    # Actually, an easier way is to just use QTimer.singleShot in enterEvent/leaveEvent,
    # or just keep it but check if underMouse. The ticket says it runs continuously.
    # Let's fix it by only running timer when underMouse.
    pass # Needs deeper look if we want to fix properly

fix_main_py()
fix_snippet_panel_py()
