agent: buffy-02
role: core
model_or_runtime: unknown
project: vacterro-fastprompter
saipen_version: 8.0.1
protocol_fingerprint: sha256:e2e83e5b9235858c329823b2b6ad75d5e27f8c21c3e16022c2cae1be5298c36a
source_head: b2fb798e66591b6adb8e769cde6f89b7d0743ccb
source_tree_fingerprint: git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
discovery_model: git-delta-v1
context_scope: SAIPEN audit, phase VERIFY
context_available: partial
report_status: complete

## RUN 1

Audit of the reviewed allowlist tools/i18n_verified_identical.json at source_head b2fb798, the artefact the last four tickets (T-1387..T-1390) all wrote into. Scope chosen because it is the one translation input that no automated check ever reads back: i18n_verified.py holds 1036 hand verdicts, validate_saitranslate.py trusts them, and nothing in the toolchain can tell a true verdict from one whose pack value moved underneath it.

Method: three scripts, each decidable without judging a language. (1) V:/_TEMP_/audit_unstated_identicals.py diffs every pack value against its en.json source and against the allowlist, in both directions, over all 32 locales and 1862 keys. (2) V:/_TEMP_/audit_verdict_split.py ranks every allowlist-covered key by how many locales translated it versus how many excused it, reducing 1036 verdicts to the 106 keys whose peers disagree. (3) Direct reads of the packs for the keys the two instruments named.

IMP-001 [P2][PROJECT_VIOLATION][reproduced][ticket] three Romanian verdicts excuse values ro.json has since translated, so a stale excuse masks a finished translation and inflates the verdict count
  expected: a verdict in tools/i18n_verified_identical.json asserts that the pack value is byte-identical to English and that English is correct for that language; when the pack value changes, the verdict is either still true or is withdrawn
  actual: ro.json holds Automat for 'Auto', Automat — Complet for 'Auto — Full' and Siloz for 'Silo', while all three are still listed under "ro" in the allowlist. They are the only three of 1036 in that state. The gate cannot see it: validate_saitranslate.py treats an excused key as translated without reading the value, so the three translated Romanian strings pass silently whether or not the excuse exists, and the "1036 verdicts" figure counts three statements that are no longer true of the pack.
  evidence: audit_unstated_identical.py, class B, prints "excused but no longer byte-identical (stale verdicts): 3" and names exactly ro 'Auto' -> 'Automat', ro 'Auto — Full' -> 'Automat — Complet', ro 'Silo' -> 'Siloz'. Confirmed by direct read: all three are present in allow["ro"], and en[key] == 'Auto' / 'Auto — Full' / 'Silo' so the identity comparison is against the right source. This is the exact mirror of T-1388, which withdrew a verdict that was false when written; this is a verdict that was true when written and stopped being true, and it survived because nothing compares the two afterwards. Repair is three deletions from the allowlist, no pack change.

IMP-002 [P3][PROJECT_VIOLATION][observed][note] 81 of 106 allowlist keys are excused in a minority of locales while the majority translate them, and no instrument ever re-reads them
  expected: the allowlist's stated contract -- "the answer is reviewed once per language and recorded here" -- is a contract about a moving pack, and the packs have moved
  actual: 81 allowlist entries sit on the minority side of their own key: excused in 1 to 12 locales while 20 to 31 translate the identical English string. This is NOT evidence that any of them is wrong. French Date, Mode, Volume, Name, Style, Silence and Archive are real French words spelled like English and are exactly this shape; i18n_verified.py's own docstring uses French Date/Mode/Volume as its worked example. The finding is about coverage, not correctness: those 81 verdicts were adjudicated against packs that have since changed, and the only re-read that has ever happened was a human noticing one of them by hand, which is how T-1388 was found.
  evidence: audit_verdict_split.py prints the full ranked table; the minority set is saved to V:/_TEMP_/audit_minority.json with per-key excused/translated counts and the excusing locale list. The discriminator T-1388 actually used -- "one locale claims English while its peers translate" -- narrows 1036 verdicts to this set but cannot separate a true French verdict from a false one, which is precisely the point i18n_verified.py makes when it says no regex can tell those apart. Re-adjudication is a per-language human judgement and is not claimed here; what is decidable is that the toolchain has no staleness assertion at all, and IMP-001 is the proof that this absence costs something real.

IMP-003 [P3][PROJECT_VIOLATION][reproduced][note] four keys are byte-identical in all 32 locales with no verdict, and they are placeholders and glyphs -- the allowlist's rule does not apply to them
  expected: i18n_verified.json's rule is "is this value still in English, and if so, is that actually right for THIS language?", which presumes the value is a word
  actual: '[{n} {res_word}]', '{name} ({n} {res_word})', '▲' and '▼' are byte-identical in every one of the 32 locales and carry no verdict anywhere. They are correctly identical -- two are pure placeholder templates and two are arrow glyphs, neither of which has a translation. They are reported as unstated verdicts by any instrument of the shape used in IMP-001, at 128 pairs (4 keys x 32 locales).
  evidence: audit_unstated_identical.py class A reports 128 unstated verdicts, and all 128 are these 4 keys in all 32 locales -- no other key appears. validate_saitranslate.py already excludes them via is_curated_neutral and so reports no problem today; the risk is to the NEXT audit, which would have to re-derive that these four are neutral rather than inheriting the fact.
