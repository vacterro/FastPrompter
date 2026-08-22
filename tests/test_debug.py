import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from fastprompter.ui.editor import VaultTextEdit


@pytest.fixture
def app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_debug(app):
    editor = VaultTextEdit(None)
    url = QUrl('javascript:alert(1)')
    safe_url = editor._safe_link_url(url)
    print('unsafe returned:', safe_url)
    url = QUrl('https://example.com')
    safe_url = editor._safe_link_url(url)
    print('safe returned:', safe_url)
