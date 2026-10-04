"""T-1409 — the Pack context menu.

Right-clicking the Pack control (or reaching Pack through the editor's
generic context menu, which is how a silo with no formatted title stays
reachable) lands here. Every action dispatches into the SAME main-window
backend the header control uses; this module owns no bundle logic of its own,
so the fallback surface cannot drift from the button.
"""

from __future__ import annotations

import os

from fastprompter.core.translations import tr


def build_bundle_menu(editor, menu, lang):
    """Append the bundle actions to ``menu`` and return the separator count.

    ``Copy Last Bundle`` is enabled only while the remembered archive still
    exists on disk: a deleted bundle must never reappear as a working action,
    and it is never silently recreated.

    T-1410: Quick Pack carries its live key as plain menu TEXT, read from
    the same binding the QShortcut is built from. Deliberately NOT
    ``QAction.setShortcut`` — that would register a second active owner of
    the chord and the menu item would fire the pack a second time.
    """
    from fastprompter.ui.shortcut_display import resolve, tooltip_with_shortcut
    win = getattr(editor, "main_win", None)

    menu.addAction(tooltip_with_shortcut(
        tr("Quick Pack", lang), resolve(win, "hk_pack_silo"), lang),
        editor._silo_bundle_dispatch_fallback)
    menu.addAction(tr("Pack Silo With Options…", lang),
                   editor._silo_bundle_dispatch_with_options)
    menu.addAction(tr("Force Repack", lang),
                   lambda: _force_repack(win, lang))
    menu.addSeparator()

    copy_action = menu.addAction(tr("Copy Last Bundle", lang),
                                 lambda: _copy_last(win, lang))
    open_last_action = menu.addAction(tr("Open Last Bundle Folder", lang),
                                      lambda: _open_last_folder(win, lang))
    menu.addAction(tr("Open Silo Exports Folder", lang),
                   lambda: _open_exports(win, lang))
    menu.addSeparator()
    menu.addAction(tr("Media-Only Quick Pack", lang),
                   lambda: _media_only(win, lang))

    last = None
    if win is not None:
        last_fn = getattr(win, "_silo_bundle_last_existing", None)
        active_fn = getattr(win, "_active_silo_id", None)
        if callable(last_fn) and callable(active_fn):
            rec = last_fn(active_fn())
            if rec and rec.get("path"):
                last = rec["path"]
        if not last:
            last = getattr(win, "_last_bundle_path", None)

    has_last = bool(last) and os.path.isfile(str(last))
    copy_action.setEnabled(has_last)
    open_last_action.setEnabled(has_last)
    return 2


def _force_repack(win, lang):
    if win is None:
        return
    repacker = getattr(win, "silo_bundle_force_repack", None)
    if callable(repacker):
        repacker()


def _open_last_folder(win, lang):
    if win is None:
        return
    opener = getattr(win, "_silo_bundle_open_last_folder", None)
    if callable(opener):
        opener()


def _open_exports(win, lang):
    if win is None:
        return
    opener = getattr(win, "_silo_bundle_open_exports", None)
    if callable(opener):
        opener()


def _copy_last(win, lang):
    if win is None:
        return
    copier = getattr(win, "_silo_bundle_copy_last", None)
    if callable(copier):
        copier()


def _media_only(win, lang):
    if win is None:
        return
    dispatch = getattr(win, "silo_bundle_media_only", None)
    if callable(dispatch):
        dispatch()
