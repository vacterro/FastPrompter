"""Fill values of a flat {english: ""} JSON batch, preserving raw key bytes exactly.

Usage:
  python _hrfill.py dump <part>       -> print "index<TAB>json-escaped-key" per entry
  python _hrfill.py fill <part> <pyfile-with-T-list>
"""
import importlib.util
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent / "batches" / "out"


def scan(text):
    """Return (entries, spans) for a flat object of string values.

    entries: list of (key, value) parsed via json.loads of the raw spans.
    spans:   list of (val_start, val_end) raw offsets of each value string literal.
    """
    i = text.index("{") + 1
    n = len(text)
    entries, spans = [], []

    def scan_string(pos):
        assert text[pos] == '"', (pos, text[pos - 20:pos + 20])
        j = pos + 1
        while j < n:
            c = text[j]
            if c == "\\":
                j += 2
                continue
            if c == '"':
                return j + 1
            j += 1
        raise ValueError("unterminated string")

    while True:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "}":
            break
        k_end = scan_string(i)
        key = json.loads(text[i:k_end])
        i = k_end
        while text[i] in " \t\r\n":
            i += 1
        assert text[i] == ":", (i, text[i - 30:i + 30])
        i += 1
        while text[i] in " \t\r\n":
            i += 1
        v_end = scan_string(i)
        val = json.loads(text[i:v_end])
        entries.append((key, val))
        spans.append((i, v_end))
        i = v_end
    return entries, spans


def dump(part):
    path = BASE / f"hr.part{part}.json"
    text = path.read_text(encoding="utf-8")
    entries, _ = scan(text)
    print(f"# {len(entries)} entries")
    for idx, (key, val) in enumerate(entries):
        assert val == "", f"entry {idx} not empty: {key!r}"
        print(f"{idx}\t{json.dumps(key, ensure_ascii=False)}")


def fill(part, listfile):
    path = BASE / f"hr.part{part}.json"
    raw = path.read_text(encoding="utf-8")
    entries, spans = scan(raw)
    spec = importlib.util.spec_from_file_location("tr", listfile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tr = mod.T
    assert len(tr) == len(entries), f"got {len(tr)} translations for {len(entries)} entries"

    out = []
    prev = 0
    for (key, _), (vs, ve), t in zip(entries, spans, tr):
        assert t, f"empty translation for {key!r}"
        assert json.dumps(t) == json.dumps(t), "not serializable"
        # placeholder parity
        for ph in ("{}", "{0}", "{name}", "{gain}", "{pct}", "{project}", "{n}", "{v}",
                   "{text}", "{time}", "{state}"):
            assert key.count(ph) == t.count(ph), f"placeholder {ph} mismatch: {key!r} -> {t!r}"
        assert key.count("{") == t.count("{"), f"brace count: {key!r} -> {t!r}"
        assert key.count("}") == t.count("}"), f"brace count: {key!r} -> {t!r}"
        assert key.count("\\n") == t.count("\\n"), f"literal-backslash-n: {key!r} -> {t!r}"
        assert key.count("\n") == t.count("\n"), f"real newline count: {key!r} -> {t!r}"
        assert key.count("\t") == t.count("\t"), f"tab count: {key!r} -> {t!r}"
        if "\t" in key:
            kl, kr = key.split("\t", 1)
            tl, tr = t.split("\t", 1)
            assert kr == tr, f"shortcut changed: {key!r} -> {t!r}"
            assert kl != tl, f"tab label not translated: {key!r}"
        for ent in ("&ndash;", "&amp;", "&rarr;", "&bull;", "&&"):
            assert key.count(ent) == t.count(ent), f"entity {ent} mismatch: {key!r} -> {t!r}"
        out.append(raw[prev:vs])
        out.append(json.dumps(t, ensure_ascii=False))
        prev = ve
    out.append(raw[prev:])
    new = "".join(out)
    path.write_text(new, encoding="utf-8", newline="")

    # verify
    check = json.loads(path.read_text(encoding="utf-8"))
    chk_entries, chk_spans = scan(path.read_text(encoding="utf-8"))
    assert len(check) == len(entries)
    assert [k for k, _ in chk_entries] == [k for k, _ in entries], "key set changed"
    for (k, v) in chk_entries:
        assert v, f"empty value: {k!r}"
    print(f"OK part{part}: {len(chk_entries)} entries, keys identical, no empty values")


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        dump(sys.argv[2])
    else:
        fill(sys.argv[2], sys.argv[3])
