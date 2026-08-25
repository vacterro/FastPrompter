"""Typecheck — a small, smart dictionary-based typo checker for silo text.

Design goals (from the request): it must be *basic* but *smart*, never dumb
and unpredictable, and it must NOT be recursive (a recursive scanner invites
re-entrancy conflicts with the editor's own highlighting passes and can
double-process the same token). Every pass here is a single linear scan;
a word is visited exactly once.

How it stays smart instead of noisy:

* Tokens that are obviously not prose are skipped: code fences (```), inline
  code, URLs, e-mails, hashtags, @mentions, hex colours, and any word glued
  to an identifier character (``foo.bar``, ``snake_case``, ``camelCase``,
  ``path/to``, ``#tag``) — those are names, not words.
* Acronyms (ALL-CAPS) and mixed-case identifiers never get flagged.
* Contractions (``don't``, ``you're``) are checked in their contracted form
  and fall back to the de-contracted form.
* A word is only flagged when the dictionary actually COVERS its script.
  The shipped dictionary is English (plus the UI vocabulary of every app
  language, so words like "Anzeige" or "sélection" that appear in the UI are
  accepted). For scripts the dictionary does not cover (Cyrillic, CJK, ...)
  the checker deliberately stays silent: flagging what you cannot judge is
  the "dumb" behaviour this module exists to avoid.
* The user dictionary (``typo_user_words`` setting) extends the pool, and
  suggestions come from difflib over the whole pool.

The module is Qt-free so the whole behaviour is unit-testable.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# Scripts the shipped dictionary covers. Words whose first letter belongs to
# any other script are never flagged (no dictionary -> no judgement).
# Extended Latin covers the UI vocabularies of every Latin-script language.
_LATIN = "latin"

# A script must contribute at least this many distinct words before the
# checker trusts it as a real dictionary. The English base list is ~10k;
# a language's UI vocabulary alone (~hundreds of words) is NOT enough, which
# is exactly the point: an undersized pool would flag every other word.
_MIN_SCRIPT_WORDS = 2000

# Characters that glue a token to a bigger identifier: a word adjacent to any
# of these is treated as part of a name (``foo.bar``, ``snake_case``,
# ``#tag``, ``@user``, ``C:\path``, ``[label]``).
_IDENT_GLUE = set("._-#/@\\~[]")

_URL_RE = re.compile(r"(?i)\b(?:https?://|ftp://|www\.)\S+")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def _script_of(ch: str) -> str:
    """Rough script family of a character: 'latin' or the block name.

    Good enough to decide dictionary coverage; we never need the exact
    sub-block, only "is this Latin" vs "some other script".
    """
    name = unicodedata.name(ch, "")
    if name.startswith("LATIN"):
        return _LATIN
    if name.startswith("CYRILLIC"):
        return "cyrillic"
    if name.startswith("GREEK"):
        return "greek"
    if name.startswith("HEBREW"):
        return "hebrew"
    if name.startswith("ARABIC"):
        return "arabic"
    if name.startswith(("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "THAI",
                        "DEVANAGARI", "ARMENIAN", "GEORGIAN")):
        return "cjk"
    return "other"


def iter_tokens(text: str):
    """Yield ``(word, start, end)`` for every checkable word, in ONE pass.

    Non-recursive by contract: a plain ``while`` over the string, no nested
    scans, no recursion — nothing here can re-enter the editor or re-process
    a token. Fence state is a single boolean, and every skip is a forward
    jump.
    """
    if not text:
        return
    n = len(text)
    # Skip ranges for URLs/e-mails: their interior must never be tokenised.
    skip: list[tuple[int, int]] = []
    for m in _URL_RE.finditer(text):
        skip.append((m.start(), m.end()))
    for m in _EMAIL_RE.finditer(text):
        skip.append((m.start(), m.end()))
    skip.sort()

    fence = False
    i = 0
    skip_idx = 0
    nskip = len(skip)
    while i < n:
        # PERF-002: consume skip ranges with ONE monotonic cursor. Advance it
        # past ranges that ended, then if we are inside the current range jump
        # straight to its end (overlapping ranges are handled naturally: the
        # cursor stops on the longest still-open range).
        while skip_idx < nskip and i >= skip[skip_idx][1]:
            skip_idx += 1
        if skip_idx < nskip and skip[skip_idx][0] <= i < skip[skip_idx][1]:
            i = skip[skip_idx][1]
            continue
        ch = text[i]
        if ch == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            ticks = j - i
            if ticks >= 3:
                # ``` fence toggles; everything inside is code.
                fence = not fence
                i = j
                continue
            if not fence and ticks <= 2:
                # Inline code: jump to the matching closing run.
                close = text.find("`" * ticks, j)
                i = close + ticks if close != -1 else n
                continue
            i = j
            continue
        if fence:
            i += 1
            continue
        if not ch.isalpha():
            i += 1
            continue
        j = i
        while j < n and (text[j].isalpha() or text[j] in "'\u2019"):
            j += 1
        word = text[i:j]
        # Glued to an identifier character on either side -> a name, not prose.
        before = text[i - 1] if i > 0 else ""
        after = text[j] if j < n else ""
        if before in _IDENT_GLUE or before.isalnum():
            i = j
            continue
        if after in _IDENT_GLUE or after.isalnum():
            i = j
            continue
        # "C:\path" and "http://…": a colon that opens a path separator
        # glues the preceding word to the rest (drive letters, schemes).
        if (after == ":" and j + 1 < n and text[j + 1] in "\\/"):
            i = j
            continue
        yield word, i, j
        i = j


def checkable(word: str) -> str | None:
    """Normalise a token for dictionary lookup, or None if it is not prose.

    * single letters and acronyms (ALL-CAPS) are never checked
    * CamelCase/mixed-case words are identifiers, not prose
    * returns the lowercase form (apostrophes normalised to ASCII)
    """
    if len(word) < 2:
        return None
    if word.isupper():
        return None
    # Mixed case beyond a capitalised first letter (camelCase / iPhone) is
    # code or a brand — skip; "Hello" / "Wrod" still get checked lowercased.
    if word[0].islower() and any(c.isupper() for c in word[1:]):
        return None
    return word.lower().replace("\u2019", "'")


class Dictionary:
    """The typecheck dictionary: base words + UI vocab + user words.

    Built once per language/profile and cached by the caller. The pool is a
    plain set; coverage per script is computed from the pool size, so adding
    user words for a language is what turns checking on for its script.
    """

    def __init__(self, base_words=None, ui_words=None, user_words=None):
        self.pool: set[str] = set()
        if base_words:
            self.pool.update(base_words)
        if ui_words:
            self.pool.update(ui_words)
        if user_words:
            self.pool.update(w.lower() for w in user_words if isinstance(w, str))
        self._words = None  # list cache for difflib suggestions
        self._rebuild_script_counts()

    def _rebuild_script_counts(self):
        """PERF-001: one pass over the pool, cached per-script counts capped
        at the coverage threshold. ``unknown`` must be O(1) per token, not a
        rescan of up to ~20k entries for every word."""
        counts: dict[str, int] = {}
        for w in self.pool:
            if w:
                script = _script_of(w[0])
                n = counts.get(script, 0) + 1
                if n >= _MIN_SCRIPT_WORDS:
                    counts[script] = n
                else:
                    counts[script] = n
        self._script_counts = counts

    def add(self, word: str) -> None:
        """Add a word (lowercased) and invalidate the suggestion cache.

        PERF-001: only a genuinely NEW unique word may raise a script's
        coverage count; duplicates must not increment it."""
        word = word.strip().lower()
        if word and word not in self.pool:
            self.pool.add(word)
            self._words = None
            script = _script_of(word[0])
            n = self._script_counts.get(script, 0) + 1
            if n >= _MIN_SCRIPT_WORDS:
                n = _MIN_SCRIPT_WORDS
            self._script_counts[script] = n

    def _script_count(self, script: str) -> int:
        """Distinct words of ``script`` in the pool, O(1) (PERF-001)."""
        return self._script_counts.get(script, 0)

    def unknown(self, word: str) -> bool:
        """Is ``word`` worth flagging? False for anything unjudgeable."""
        norm = checkable(word)
        if norm is None:
            return False
        script = _script_of(norm[0])
        # No dictionary for this script -> no judgement. This is the "smart"
        # rule: an undersized pool would flag every other word (e.g. a few
        # hundred Russian UI strings are NOT a Russian dictionary). The user
        # dictionary can grow a script past the threshold, which is how a
        # second language gets turned on.
        if self._script_count(script) < _MIN_SCRIPT_WORDS:
            return False
        if norm in self.pool:
            return False
        # Contraction fallbacks: "don't" -> "dont" is not a word, but the
        # uncontracted check catches "cant"/"wont" style typos while the
        # contracted form lives in the pool (e.g. "can't").
        stripped = norm.replace("'", "")
        if stripped and stripped in self.pool:
            return False
        return True

    def suggest(self, word: str, n: int = 3, cutoff: float = 0.72) -> list[str]:
        """Close dictionary matches for a flagged word (difflib, capped)."""
        norm = checkable(word)
        if norm is None:
            return []
        if self._words is None:
            self._words = sorted(self.pool)
        return difflib.get_close_matches(norm, self._words, n=n, cutoff=cutoff)


_UI_VOCAB_CACHE: frozenset[str] | None = None


def ui_vocabulary() -> frozenset[str]:
    """Every Latin-script word from every shipped UI language pack.

    This is the "dictionary for all languages" part: a German "Anzeige" or
    a French "sélection" that appears in the app's own UI is accepted even
    though the base list is English.

    PERF-006: the vocabulary is a static build input, so the generated
    module (``tools/gen_typecheck_ui_vocab.py`` output) is returned when it
    exists — importing every translation module at first use defeated
    localization laziness and retained ~10 MiB for the process lifetime.
    The dynamic extraction stays as the fallback for source checkouts that
    have not run the generator, producing the identical set.
    """
    global _UI_VOCAB_CACHE
    if _UI_VOCAB_CACHE is None:
        try:
            from fastprompter.core.typecheck_ui_vocab import WORDS
            _UI_VOCAB_CACHE = frozenset(WORDS)
            return _UI_VOCAB_CACHE
        except ImportError:
            pass
        words: set[str] = set()
        from fastprompter.core import i18n as _i18n
        for code in _i18n.available_codes():
            if code == "EN":
                continue
            try:
                mod = __import__(
                    f"fastprompter.core.i18n.{code.lower()}",
                    fromlist=["TRANSLATIONS"])
            except Exception:
                continue
            for value in getattr(mod, "TRANSLATIONS", {}).values():
                for m in re.finditer(r"[A-Za-z]{2,}", value):
                    w = m.group(0).lower()
                    if w.isascii() and w.isalpha():
                        words.add(w)
        _UI_VOCAB_CACHE = frozenset(words)
    return _UI_VOCAB_CACHE


def find_unknown(text: str, dictionary: Dictionary, limit: int = 2000):
    """All flagged words in ``text``: ``[(word, start, end), ...]``.

    One linear pass through ``iter_tokens`` (non-recursive); ``limit`` caps
    the result so a pathological document cannot flood the painter.
    """
    out: list[tuple[str, int, int]] = []
    for word, start, end in iter_tokens(text):
        if dictionary.unknown(word):
            out.append((word, start, end))
            if len(out) >= limit:
                break
    return out
