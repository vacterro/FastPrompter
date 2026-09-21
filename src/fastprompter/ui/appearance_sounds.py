"""T-1245: semantic UI appearance sound emitters.

Every function here reports ONE kind of appearance transition to
``SoundManager.play_appearance``. The contract is deliberate and narrow:

* call when a user-visible surface becomes visible (hidden -> shown, or
  the first presentation of a freshly created surface);
* never call for construction, relayout, paint events, language
  reapplication, an internal refresh of a hidden widget, dialog child
  control initialization, re-delivery of the same show signal, or
  hover-card geometry changes while the card is already visible.

Each surface keeps exactly ONE semantic owner: a dialog that owns a more
specific event (the Audio Hub -> ``audio_hub_show``) is excluded from the
generic ``dialog_show`` by an instance tag, so one appearance never fires
two sounds.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QDialog, QWidget

from fastprompter.core.logging import logger

#: Instance tag marking dialogs/panels that own a MORE SPECIFIC appearance
#: event than the generic ``dialog_show`` / ``panel_show``. Double-fire
#: prevention: the generic emitter skips any object carrying it.
SPECIFIC_APPEARANCE_ATTR = "_t1245_own_appearance_event"


def _emit(main_win, event: str) -> None:
    manager = getattr(main_win, "sound_manager", None)
    if manager is None:
        return
    try:
        manager.play_appearance(event)
    except Exception:
        logger.debug("appearance sound %s failed", event, exc_info=True)


def emit_app_show(main_win) -> None:
    """The application window became visible for a NEW visible cycle."""
    _emit(main_win, "app_show")


def emit_settings_show(main_win) -> None:
    """The mini/settings panel transitioned hidden -> visible."""
    _emit(main_win, "settings_show")


def emit_audio_hub_show(main_win) -> None:
    """The Sound Settings / Audio Hub dialog became visibly presented."""
    _emit(main_win, "audio_hub_show")


def emit_dialog_show(main_win, dialog) -> None:
    """A generic eligible dialog was presented (hidden/absent -> visible).

    Dialogs owning a specific event carry SPECIFIC_APPEARANCE_ATTR and are
    skipped here: one appearance, one cue.
    """
    if getattr(dialog, SPECIFIC_APPEARANCE_ATTR, None):
        return
    _emit(main_win, "dialog_show")


def emit_panel_show(main_win, panel) -> None:
    """An eligible panel transitioned hidden -> visible."""
    if getattr(panel, SPECIFIC_APPEARANCE_ATTR, None):
        return
    _emit(main_win, "panel_show")


def emit_notification_show(main_win) -> None:
    """A notification surface became visible."""
    _emit(main_win, "notification_show")


def emit_hover_card_show(main_win) -> None:
    """A hover card transitioned hidden/nonexistent -> visible."""
    _emit(main_win, "hover_card_show")


class AppearanceShowFilter(QObject):
    """Application-level QEvent.Show reporter for generic dialogs/panels.

    Same trick as ScrollSoundFilter/ButtonClickSoundFilter: one app-level
    filter reaches every QDialog and top-level panel without each dialog
    remembering to wire itself. QEvent.Show only arrives for a real
    visible transition (construction while hidden, internal refresh and
    relayout of hidden widgets never produce one), and the manager's
    dedupe window folds the rare double delivery (Show + showEvent from
    two code paths for the same appearance) into one cue.

    Dialogs that own a more specific appearance event are tagged with
    SPECIFIC_APPEARANCE_ATTR and skipped, so no appearance ever double-
    fires generic + specific.
    """

    def __init__(self, sound_manager, main_win=None):
        super().__init__()
        self._sound_manager = sound_manager
        self._main_win = main_win

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Show:
            return False
        try:
            widget = obj if isinstance(obj, QWidget) else None
            if widget is None or not widget.isVisible():
                return False
            # Never let the filter's own bookkeeping play sounds: the main
            # window is app_show's owner, the Audio Hub is audio_hub_show's.
            main = self._main_win
            if widget is main:
                return False
            if isinstance(obj, QDialog):
                if not getattr(obj, SPECIFIC_APPEARANCE_ATTR, None):
                    self._emit("dialog_show")
            elif widget.isWindow() and getattr(obj, SPECIFIC_APPEARANCE_ATTR,
                                               None) == "panel_show_eligible":
                self._emit("panel_show")
        except Exception:
            logger.debug("appearance show filter failed", exc_info=True)
        return False

    def _emit(self, event: str) -> None:
        try:
            self._sound_manager.play_appearance(event)
        except Exception:
            logger.debug("appearance sound %s failed", event, exc_info=True)
