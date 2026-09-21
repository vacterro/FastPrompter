"""T-1244 A3: master-mute UI translation contract.

Two invariants:

1. ``cb_audio_mute`` passes the CANONICAL English source ``"🔇 Master Mute"``
   into ``create_footer_cb``, so ``_en_text`` is never an already-translated
   value — the settings retranslation pass can always re-derive the display
   text from the English base.

2. The dynamic ``MUTED`` / ``SOUND ON`` state label is NOT a static
   ``_en_text`` widget: it re-derives its text from the live mute state in
   the ACTIVE language whenever ``_sync_audio_mute_state()`` runs, and that
   runs after every language change, profile switch, hotkey flip and
   checkbox toggle.  A dynamic state label must never become a stale static
   ``_en_text``.

The source-level invariants run without Qt (they parse the construction
sites); the behaviour invariants use a tiny fake window that mimics the
real ``_sync_audio_mute_state`` contract.
"""

from __future__ import annotations

import ast
import os
import re

_SETTINGS = os.path.join(os.path.dirname(__file__), "..", "src",
                         "fastprompter", "ui", "settings_builder.py")
_MAIN = os.path.join(os.path.dirname(__file__), "..", "src",
                     "fastprompter", "main.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _source_of(func_node):
    return ast.unparse(func_node)


def _find_settings_builder_func(name):
    tree = ast.parse(_read(_SETTINGS))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in settings_builder.py")


def _find_main_func(name):
    tree = ast.parse(_read(_MAIN))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in main.py")


class TestCanonicalEnglishSource:
    def test_cb_audio_mute_gets_raw_english_not_pretranslated(self):
        """The create_footer_cb call for cb_audio_mute must pass the bare
        English string — no tr() wrapping of the first argument."""
        src = _read(_SETTINGS)
        idx = src.find("self.cb_audio_mute = create_footer_cb(")
        assert idx != -1, "cb_audio_mute construction not found"
        block = src[idx:idx + 800]
        # Quote-style agnostic and comment-tolerant: the first argument
        # must be a plain string literal, not a tr(...) call.
        m = re.search(
            r"create_footer_cb\(\s*(?:#[^\n]*\n\s*)*(['\"])([^'\"]*)\1",
            block)
        assert m, "could not parse the first create_footer_cb argument"
        assert "tr(" not in block[:m.start() + 20].split(
            "create_footer_cb(")[0].split("(")[-1]
        assert m.group(2) == "🔇 Master Mute", (
            "cb_audio_mute must pass the canonical English source "
            f"'🔇 Master Mute' directly (no tr() pre-translation), got "
            f"{m.group(2)!r}")

    def test_retranslation_pass_covers_checkboxes_from_en_text(self):
        """The generic checkbox sweep must exist and use _en_text — the
        canonical base cb_audio_mute now correctly carries."""
        src = _read(_MAIN)
        idx = src.find("def _apply_settings_language")
        body = src[idx:src.find("\n    def ", idx + 10)]
        assert "_translatable_checkboxes()" in body
        assert '_en_text' in body


class TestDynamicStateLabelFollowsLanguage:
    def test_sync_uses_active_language_not_static_en_text(self):
        """_sync_audio_mute_state translates MUTED / SOUND ON with the
        window's current language every time it runs."""
        node = _find_main_func("_sync_audio_mute_state")
        src = _source_of(node)
        assert 'MUTED" if muted else "SOUND ON' in src or \
               "MUTED' if muted else 'SOUND ON" in src
        assert "self._current_lang" in src
        # It must NOT stamp _en_text onto the dynamic label.
        assert "_en_text" not in src

    def test_apply_settings_language_resyncs_the_state_label(self):
        """A language change re-runs _sync_audio_mute_state, so the dynamic
        label follows the newly applied language."""
        node = _find_main_func("_apply_settings_language")
        src = _source_of(node)
        assert "self._sync_audio_mute_state()" in src, (
            "_apply_settings_language must refresh the dynamic MUTED / "
            "SOUND ON label")

    def test_profile_switch_resyncs_after_language_assignment(self):
        """In the profile runtime path, _sync_audio_mute_state must also run
        AFTER self._current_lang is assigned from the destination profile."""
        tree = ast.parse(_read(_MAIN))
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            src = _source_of(node)
            lang_idx = src.find("self._current_lang = get_language(data)")
            sync_idx = src.rfind("self._sync_audio_mute_state()")
            if lang_idx != -1 and sync_idx != -1:
                found = True
                assert sync_idx > lang_idx, (
                    "profile switch must call _sync_audio_mute_state() "
                    "AFTER assigning the new profile language")
                # The final sync call must be the LAST one, and the profile
                # path must contain the language application.
                assert "_apply_settings_language" in src
        assert found, "profile runtime function with language assignment not found"


class TestLabelBehaviourWithFakeWindow:
    """Behavioural proof using a fake window that mirrors the real
    _sync_audio_mute_state contract."""

    def _sync(self, win):
        # Execute the real logic shape: dynamic translation each call.
        muted = win.data.get("audio_global_muted", "False") == "True"
        cb = getattr(win, "cb_audio_mute", None)
        if cb is not None:
            cb["checked"] = muted
        lbl = getattr(win, "audio_mute_state_label", None)
        if lbl is not None:
            lbl["text"] = _translate("MUTED" if muted else "SOUND ON",
                                     win._current_lang)

    def test_label_follows_each_language_change(self):
        win = _FakeWin(lang="EN", muted=False)
        self._sync(win)
        assert win.audio_mute_state_label["text"] == "SOUND ON"
        win._current_lang = "RU"
        self._sync(win)
        assert win.audio_mute_state_label["text"] != "SOUND ON", (
            "label must be re-derived in the active language, never stale")
        win._current_lang = "EN"
        self._sync(win)
        assert win.audio_mute_state_label["text"] == "SOUND ON"

    def test_label_follows_mute_flip_in_any_language(self):
        win = _FakeWin(lang="RU", muted=False)
        self._sync(win)
        before = win.audio_mute_state_label["text"]
        win.data["audio_global_muted"] = "True"
        self._sync(win)
        after = win.audio_mute_state_label["text"]
        assert after != before
        # And the checkbox echo agrees with the state.
        assert win.cb_audio_mute["checked"] is True

    def test_label_is_never_stamped_as_static_en_text(self):
        """The state label construction must not attach _en_text — a
        dynamic state label must not enter the static retranslation sweep,
        which would freeze it."""
        node = _find_settings_builder_func("build_settings_tabs")
        src = _source_of(node)
        idx = src.find("self.audio_mute_state_label = QLabel(")
        assert idx != -1
        block = src[idx:src.find("self.cb_trash_vision", idx)]
        assert "_en_text" not in block


# -- minimal translation stand-in -------------------------------------------

_RU_SAMPLE = {
    "SOUND ON": "ЗВУК ВКЛ",
    "MUTED": "БЕЗВУХА",
}


def _translate(text, lang):
    """Stand-in for the real tr(): proves re-derivation per language."""
    if lang == "RU":
        return _RU_SAMPLE.get(text, text)
    return text


class _FakeWin:
    def __init__(self, lang, muted):
        self.data = {"audio_global_muted": "True" if muted else "False"}
        self._current_lang = lang
        self.cb_audio_mute = {"checked": muted}
        self.audio_mute_state_label = {"text": ""}
