import os

# Run all Qt tests headless. Without a platform plugin the GUI tests fail to
# construct a QApplication on a machine with no display; the offscreen platform
# is the standard headless backend and exercises the same code paths.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True, scope="session")
def mute_sounds():
    """Silence all tests by mocking the underlying audio players."""
    patches = []
    
    try:
        import winsound
        patches.append(patch("fastprompter.core.sound_manager.winsound"))
    except ImportError:
        pass

    try:
        from PyQt6.QtMultimedia import QSoundEffect
        patches.append(patch.object(QSoundEffect, 'play'))
    except ImportError:
        pass
        
    for p in patches:
        try:
            p.start()
        except Exception:
            pass
            
    yield
    
    for p in reversed(patches):
        try:
            p.stop()
        except Exception:
            pass
