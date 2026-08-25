"""PERF-006 (audit acb-mt632rjw): the typecheck UI vocabulary is a static
generated build input, not a runtime import of every i18n language pack."""

import builtins
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import typecheck as tc


def _dynamic_extraction():
    """Independent re-extraction under the documented rules."""
    import re

    from fastprompter.core import i18n as _i18n
    words = set()
    for code in _i18n.available_codes():
        if code == "EN":
            continue
        mod = __import__(f"fastprompter.core.i18n.{code.lower()}",
                         fromlist=["TRANSLATIONS"])
        for value in getattr(mod, "TRANSLATIONS", {}).values():
            for m in re.finditer(r"[A-Za-z]{2,}", value):
                w = m.group(0).lower()
                if w.isascii() and w.isalpha():
                    words.add(w)
    return frozenset(words)


def test_generated_vocabulary_equals_source_extraction():
    from fastprompter.core.typecheck_ui_vocab import WORDS
    assert frozenset(WORDS) == _dynamic_extraction()


def test_ui_vocabulary_imports_no_language_modules(monkeypatch):
    import fastprompter.core.typecheck_ui_vocab as gen

    monkeypatch.setattr(tc, "_UI_VOCAB_CACHE", None)
    before = set(sys.modules)
    vocab = tc.ui_vocabulary()
    new_i18n = [m for m in set(sys.modules) - before if ".i18n." in m]
    assert vocab == frozenset(gen.WORDS)
    assert not new_i18n, new_i18n


def test_fallback_path_matches_generated_set(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "fastprompter.core.typecheck_ui_vocab":
            raise ImportError("generated module blocked for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.setattr(tc, "_UI_VOCAB_CACHE", None)
    vocab = tc.ui_vocabulary()
    assert vocab == _dynamic_extraction()


def test_base_words_and_user_words_stay_independent():
    from fastprompter.core.typecheck_words import BASE_WORDS
    d = tc.Dictionary(base_words=BASE_WORDS,
                      ui_words=tc.ui_vocabulary(),
                      user_words=["zzqxword"])
    assert "zzqxword" in d.pool
    # a UI word is accepted without being an English base word
    ui_only = next(w for w in tc.ui_vocabulary() if w not in BASE_WORDS)
    assert ui_only in d.pool
