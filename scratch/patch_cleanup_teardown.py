import glob
import re

target_files = glob.glob(r"tests_smoke\test_*.py")

for filepath in target_files:
    with open(filepath, encoding='utf-8') as f:
        content = f.read()

    # Find the def win(monkeypatch): block
    # and we want to replace everything from `w.conn = None` to the end of the fixture
    
    # We will use a regex to match the fixture definition until the end of its indentation
    # Actually, let's just find the `w.conn = None` line inside the fixture and truncate there, appending our robust teardown
    
    def replacement_func(m):
        return m.group(1) + """w.conn = None
    w.hide()
    
    # Cancel any pending extra selection updates to prevent segfaults
    if getattr(w, "text_area", None) and getattr(w.text_area, "_sel_refresh_pending", False):
        w.text_area._sel_refresh_pending = False
        
    w.deleteLater()
    
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QEvent
    QApplication.instance().setStyleSheet("") # Clear global stylesheet to prevent crashes on dead widgets
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()"""

    # We match `@pytest.fixture...` up to `w.conn = None` and any subsequent statements in that block
    new_content = re.sub(
        r'(@pytest\.fixture[^\n]*\ndef win[^\n]*\n(?:[ \t]+.*?\n)*?[ \t]+w\.conn = None\n)(?:[ \t]+w\.[^\n]+\n|[ \t]+from[^\n]+\n|[ \t]+QApplication[^\n]+\n|[ \t]+QCoreApplication[^\n]+\n|[ \t]+if getattr[^\n]+\n|[ \t]+w\.text_area[^\n]+\n|[ \t]+#[^\n]+\n)*',
        replacement_func,
        content
    )
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Cleaned up fixture teardown in {filepath}")
    else:
        print(f"No changes in {filepath}")
