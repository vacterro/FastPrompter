"""Fix T-152 and T-153.

T-152: Add logging to bare excepts in critical paths (state.py JSON loading, 
       settings.py custom_colors, hotkeys.py VkKeyScanW)
T-153: Skip setWindowFlags when flags haven't actually changed
"""

import os

PROJECT = r"v:\___VAC\__K\__CODE\_PY\_FastPrompter"


def fix_state_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "core", "state.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    changes = 0

    # T-152: Replace silent `except Exception: self.data[row[0]] = {}` with logged version
    # The JSON loading blocks where data could be silently corrupted
    replacements = [
        # cats_order
        ('                    except Exception: self.data[row[0]] = {}',
         '                    except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = {}'),
        # silo_last_edited 
        ('                except Exception: self.data[row[0]] = {}',
         '                except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = {}'),
        # pinned_silos, silo_ticked, silo_collapsed
        ('                    except Exception: self.data[row[0]] = []',
         '                    except Exception as e: logger.warning(f"Failed to parse {row[0]}: {e}"); self.data[row[0]] = []'),
        # custom_colors middle try
        ('                    except Exception:',
         '                    except (json.JSONDecodeError, SyntaxError) as e: logger.warning(f"Failed to parse custom_colors via json: {e}");'),
    ]
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new, 1)
            changes += 1
            print(f"state.py: replaced bare except ({old[:50]}...)")
        else:
            print(f"state.py: SKIP — not found: {old[:50]}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"state.py: {changes} changes")


def fix_main_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "main.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    changes = 0

    # T-153: Skip setWindowFlags recreation when flags haven't changed
    old_apply = (
        '    def apply_window_flags(self, _=None):\n'
        '        self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"\n'
        '        self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"\n'
        '        flags = Qt.WindowType.Window\n'
        '        normal = self.cb_normal_window.isChecked()\n'
        '        if not normal:\n'
        '            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool\n'
        '        self.unregister_all_hotkeys()\n'
        '        was_visible = self.isVisible()\n'
        '        # setWindowFlags recreates the native window; the resulting\n'
        '        # activation-change would trigger the click-out auto-hide and make\n'
        '        # the toggle look broken. Suppress it until the dust settles.\n'
        '        self.ignore_focus_loss = True\n'
        '        geo = self.geometry()\n'
        '        # Anti-flashbang: the recreated native window first paints with the\n'
        '        # default (white) background brush before the stylesheet kicks in.\n'
        '        # Paint it in the theme\'s window color instead.\n'
        '        m_bg = re.search(\n'
        '            r"QWidget\\s*\\{[^}]*background-color:\\s*(#[0-9a-fA-F]{3,8})",\n'
        '            QApplication.instance().styleSheet(),\n'
        '        )\n'
        '        if m_bg:\n'
        '            from PyQt6.QtGui import QPalette\n'
        '            pal = self.palette()\n'
        '            pal.setColor(QPalette.ColorRole.Window, QColor(m_bg.group(1)))\n'
        '            self.setPalette(pal)\n'
        '            self.setAutoFillBackground(True)\n'
        '        self.setUpdatesEnabled(False)\n'
        '        self.hide()  # explicit hide forces a clean native-frame rebuild\n'
        '        self.setWindowFlags(flags)\n'
        '        self.setGeometry(geo)'
    )

    new_apply = (
        '    def apply_window_flags(self, _=None):\n'
        '        self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"\n'
        '        self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"\n'
        '        flags = Qt.WindowType.Window\n'
        '        normal = self.cb_normal_window.isChecked()\n'
        '        if not normal:\n'
        '            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool\n'
        '        # Skip HWND recreation if flags haven\'t actually changed\n'
        '        current = self.windowFlags()\n'
        '        if current == flags:\n'
        '            # Only AOT state may differ — handle via SetWindowPos\n'
        '            if self._always_on_top:\n'
        '                try:\n'
        '                    ctypes.windll.user32.SetWindowPos(\n'
        '                        int(self.winId()), -1, 0, 0, 0, 0, 0x0002 | 0x0001\n'
        '                    )\n'
        '                except Exception:\n'
        '                    pass\n'
        '            return\n'
        '        self.unregister_all_hotkeys()\n'
        '        was_visible = self.isVisible()\n'
        '        # setWindowFlags recreates the native window; the resulting\n'
        '        # activation-change would trigger the click-out auto-hide and make\n'
        '        # the toggle look broken. Suppress it until the dust settles.\n'
        '        self.ignore_focus_loss = True\n'
        '        geo = self.geometry()\n'
        '        # Anti-flashbang: the recreated native window first paints with the\n'
        '        # default (white) background brush before the stylesheet kicks in.\n'
        '        # Paint it in the theme\'s window color instead.\n'
        '        m_bg = re.search(\n'
        '            r"QWidget\\s*\\{[^}]*background-color:\\s*(#[0-9a-fA-F]{3,8})",\n'
        '            QApplication.instance().styleSheet(),\n'
        '        )\n'
        '        if m_bg:\n'
        '            from PyQt6.QtGui import QPalette\n'
        '            pal = self.palette()\n'
        '            pal.setColor(QPalette.ColorRole.Window, QColor(m_bg.group(1)))\n'
        '            self.setPalette(pal)\n'
        '            self.setAutoFillBackground(True)\n'
        '        self.setUpdatesEnabled(False)\n'
        '        self.hide()  # explicit hide forces a clean native-frame rebuild\n'
        '        self.setWindowFlags(flags)\n'
        '        self.setGeometry(geo)'
    )

    if old_apply in content:
        content = content.replace(old_apply, new_apply, 1)
        changes += 1
        print("T-153: apply_window_flags now skips HWND recreation when flags unchanged")
    else:
        print("T-153: SKIP — apply_window_flags pattern not found (may differ slightly)")
        # Try to find the method
        idx = content.find("def apply_window_flags")
        if idx >= 0:
            print(f"  Found at position {idx}")
        else:
            print("  apply_window_flags not found at all")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"main.py: {changes} changes")


def fix_settings_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "ui", "settings.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    changes = 0

    # T-152: Add logging to silent `except Exception: pass` in ColorConfigDialog
    old = ("            import ast\n"
           "            try: cc = ast.literal_eval(cc)\n"
           "            except Exception: pass")
    new = ("            import ast\n"
           "            try: cc = ast.literal_eval(cc)\n"
           "            except Exception as e:\n"
           "                from fastprompter.core.logging import logger\n"
           "                logger.debug(f\"Failed to parse custom_colors: {e}\")")
    if old in content:
        content = content.replace(old, new, 1)
        changes += 1
        print("settings.py: added logging to custom_colors parsing")
    else:
        print("settings.py: SKIP — pattern not found")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"settings.py: {changes} changes")


def fix_hotkeys_py():
    path = os.path.join(PROJECT, "src", "fastprompter", "core", "hotkeys.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    changes = 0

    # T-152: Reduce scope of bare except in VkKeyScanW
    old = "        except Exception:\n            pass\n    # Fall back to static mapping"
    new = "        except (OSError, AttributeError, ctypes.WinError):\n            pass\n    # Fall back to static mapping"
    if old in content and "ctypes.windll" in content:
        content = content.replace(old, new, 1)
        changes += 1
        print("hotkeys.py: narrowed bare except to OSError/AttributeError")
    else:
        print("hotkeys.py: SKIP — pattern not found")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"hotkeys.py: {changes} changes")


if __name__ == "__main__":
    fix_state_py()
    fix_main_py()
    fix_settings_py()
    fix_hotkeys_py()
    print("\nAll fixes applied.")
