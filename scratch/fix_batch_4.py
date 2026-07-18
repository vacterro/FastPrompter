import os

PROJECT = r"v:\___VAC\__K\__CODE\_PY\_FastPrompter"

def fix_main_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "main.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # T-189, T-194, T-310: change_profile
    if "def change_profile(" in content:
        # T-310
        old_data_swap = """        self.state.switch_profile(idx + 1)
        self.data = self.state.data"""
        new_data_swap = """        self.state.switch_profile(idx + 1)
        self.data = self.state.data
        cat = self.data["cats_order"][0] if self.data.get("cats_order") else "Text"
        self.silo_last_edited = self.data.setdefault("silo_last_edited_all", {}).setdefault(cat, {})"""
        content = content.replace(old_data_swap, new_data_swap)

        # T-189
        old_build = "        self.build_categories()"
        new_build = "        self.build_categories()\n        self.text_area.document().clearUndoRedoStacks()"
        # Replace only in change_profile method body
        change_prof_idx = content.find("def change_profile(")
        if change_prof_idx > -1:
            part1 = content[:change_prof_idx]
            part2 = content[change_prof_idx:]
            part2 = part2.replace(old_build, new_build, 1)
            content = part1 + part2

        # T-194
        old_tab = """        for i, c in enumerate(self.data["cats_order"]):
            if c == "Text":"""
        new_tab = """        for i, c in enumerate(self.data["cats_order"]):
            if c in ("Text", self.data["cats_order"][0] if self.data.get("cats_order") else "Text"):"""
        content = content.replace(old_tab, new_tab)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("T-189, T-194, T-310 fixed.")

def fix_snippet_panel_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "ui", "snippet_panel.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # T-209: _update_hover_buttons calls folder_summary
    old_tooltip = """            try:
                from fastprompter.ui.file_container import folder_summary
                presets = self.main_win.data.get("temp_presets", [])
                text = presets[self.global_idx] if 0 <= self.global_idx < len(presets) else ""
                self._btn_files.setToolTip(
                    tr("Files: drop/drag/preview assets for this silo\\n\\n{}", getattr(self.main_win, "_current_lang", "EN")).format(
                    folder_summary(self.main_win._files_root(),
                                     self.main_win.get_current_category(), text, lang=self.main_win._current_lang))
                )
            # TODO: BUG: Silent blanket exception handler swallows errors

            except Exception:
                pass  # tooltip is decoration; hover must never break"""
    
    new_tooltip = """            self._btn_files.setToolTip(tr("Files: drop/drag/preview assets for this silo", getattr(self.main_win, "_current_lang", "EN")))"""
    
    if old_tooltip in content:
        content = content.replace(old_tooltip, new_tooltip)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("T-209 fixed.")

fix_main_py()
fix_snippet_panel_py()
