from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal
from .models import Settings

class AppState(QObject):
    """
    Central state manager for the application to prevent implicit cross-feature bugs.
    Features emit signals or call methods here to update global state.
    """
    settings_changed = pyqtSignal(Settings)
    lock_toggled = pyqtSignal(bool)
    always_on_top_toggled = pyqtSignal(bool)
    
    def __init__(self, initial_settings: Settings):
        super().__init__()
        self._settings = initial_settings
        self._is_locked = initial_settings.window_locked == "1"
        self._is_always_on_top = False
        self.ignore_focus_loss = False
        
    @property
    def settings(self) -> Settings:
        return self._settings

    @settings.setter
    def settings(self, new_settings: Settings):
        self._settings = new_settings
        self.settings_changed.emit(self._settings)
        
    @property
    def is_locked(self) -> bool:
        return self._is_locked
        
    @is_locked.setter
    def is_locked(self, value: bool):
        if self._is_locked != value:
            self._is_locked = value
            self._settings.window_locked = "1" if value else "0"
            self.lock_toggled.emit(value)
            
    @property
    def is_always_on_top(self) -> bool:
        return self._is_always_on_top
        
    @is_always_on_top.setter
    def is_always_on_top(self, value: bool):
        if self._is_always_on_top != value:
            self._is_always_on_top = value
            self.always_on_top_toggled.emit(value)
