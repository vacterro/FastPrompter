import sys, re, collections, json, os

sys.path.insert(0, "src")
from fastprompter.core.i18n import en

E = en.TRANSLATIONS

ph = collections.Counter()
for v in E.values():
    for m in re.findall(r"\{[^}]*\}", v):
        ph[m] += 1
print("brace placeholders:", len(ph), "distinct")
for m, c in ph.most_common(20):
    print("   ", repr(m), c)

amp = [v for v in E.values() if "&" in v]
print("values containing ampersand:", len(amp))
for v in amp[:25]:
    print("   ", repr(v))

tab = [v for v in E.values() if "\t" in v]
print("values containing tab:", len(tab))
for v in tab[:12]:
    print("   ", repr(v))

nl = [v for v in E.values() if "\n" in v]
print("values containing newline:", len(nl))

emo = [v for v in E.values() if re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", v)]
print("values containing emoji/symbol:", len(emo))
