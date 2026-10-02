agent: buffy-01
role: core
model_or_runtime: unknown
project: vacterro-fastprompter
saipen_version: 8.0.1
protocol_fingerprint: sha256:e2e83e5b9235858c329823b2b6ad75d5e27f8c21c3e16022c2cae1be5298c36a
source_head: b053bff132aa8b2ee2a0540fad3f533355dfe103
source_tree_fingerprint: git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
discovery_model: git-delta-v1
context_scope: SAIPEN audit, phase DONE
context_available: partial
report_status: complete

## RUN 1

Audit scope: the git delta at b053bff -- T-1379's Limit-UI tr() wrapping
(b2f845a, 8ef6d03) and T-1384's 32-locale campaign (b053bff). Method: read the
shipped source at HEAD and confirm every claim against the CONSUMER of a value
rather than its producer, cross-check each wrapped literal against all 33 packs
in .saipen/saitranslate/locales/, AST-walk the tr()/tr_fmt() call sites, and run
the conformance gate inside a detached worktree at HEAD rather than in the
working tree. Four findings, three of which are defects the session that wrote
the code did not see.

IMP-001 [P1][PROJECT_VIOLATION][reproduced][ticket] T-1379 was closed on an audit that structurally could not see the largest untranslated surface
expected: every user-facing string the Limit UI paints is wrapped in tr(), so a non-English locale renders no raw English in the overview, the gauges, the hover card, the account selector or the settings dialog
actual: the audit that justified closure excluded any literal matching is_markup() -- r"<[/a-zA-Z]|\bstyle\s*=|\bcolor\s*:\s*#|font-weight|..." -- and then reported the excluded set as "not prose". Every hover-card string contains a tag, so that regex classified the entire hover card as markup. Markup in a translatable position still has translatable text inside it; only the tag itself has to stay raw. Confirmed at HEAD: limit_gauges.py:851-858 returns bare "updated now" and "updated {n}m ago"; limit_overview.py:525-527 paints "{n}% left" / "{n}% used" through QPainter and :563-568 paints "resets now" / "resets in {n}m"; limit_settings_dialog.py:1235-1241 builds all 17 Colours-tab labels and tooltips from limit_colors.ROLES as raw English, and "Healthy quota" is absent from every one of the 33 packs, so the Colours tab is 100% English in every non-English locale. Roughly forty distinct strings across three of the five surfaces the ticket named.
evidence: sed of the three regions at HEAD b053bff returns the bare literals quoted above; grep for "Healthy quota" across .saipen/saitranslate/locales/*.json returns no hit in any of the 33 packs. Reproduce with: sed -n '851,858p' src/fastprompter/ui/limit_gauges.py; sed -n '523,528p' src/fastprompter/ui/limit_overview.py; sed -n '1233,1243p' src/fastprompter/ui/limit_settings_dialog.py. Filed as T-1385.

IMP-002 [P1][PROJECT_VIOLATION][reproduced][ticket] an English pluralization placeholder is injected through tr(), so every non-English locale renders a bare English "s" glued to a foreign noun
expected: a counted noun agrees with its number in the target language, or the counting is delegated to a per-language plural helper at the call site
actual: limit_settings_dialog.py:477-479 computes res_suffix = "s" if banked_total != 1 else "" in Python and pastes it into tr("Activate reset ({n} reset{s})"); :482-484 does the same for tr("Open Usage ({n} reset{s})"). The {s} token is present verbatim in all 33 packs, so no translator can repair it -- a translator sees {s} and preserves it. RU renders "Активировать сброс (3 сбросs)" and UKR "Активувати скидання (3 скиданьs)" on the primary button of the AI Limit Settings dialog, on every refresh with banked_total != 1. Weaker same root cause at :250/:256 and limit_gauges.py:401/:407, where an English singular/plural test picks the noun before it is dropped into a slot whose grammatical case the target language fixes: the RU template "Доступно: {banked} накопленных {res_word}." yields "3 накопленных сбросы".
evidence: read of limit_settings_dialog.py:477-484 at HEAD; the {s} token appears verbatim in all 33 pack files. Recorded as a deferred ceiling in .saipen/evidence/t1384/translation_campaign.md, but it is a shipped rendering defect on a primary control rather than a documentation gap, so it is filed.

IMP-003 [P1][PROTOCOL_VIOLATION][reproduced][ticket] conformance evidence cannot be recorded at all, because two divergent SAIPEN installs both answer to VERSION 8.0.1
expected: a fresh `saipen validate` in a clean checkout mints an attributable receipt bound to the source identity, so a DONE ticket can cite current evidence
actual: `saipen validate` returns ok:false with code INSTALL_IDENTITY_MISMATCH. The running install is V:\___VAC\__K\__CODE\_AI_STUFF_AGENTIC\_SAIPEN\tools\validate.py while .saipen/STATE.md:8 names saipen_home C:/Users/vac34/.agents/skills/saipen. Both directories exist on disk and both report VERSION 8.0.1, so the engine cannot attribute evidence to a source identity and a DONE ticket cannot cite a freshly derived conformance checkpoint.
evidence: `saipen validate --json` inside a detached worktree at b053bff returns ok:false, code INSTALL_IDENTITY_MISMATCH, while the nested validator result is exit_code 0, problem_count 0, status CURRENT_PASS -- the structural result is real, only the receipt is unmintable. The same refusal appears in the main tree. Filed as T-1386. Left to a human because picking the canonical install and retiring the other rewrites the protocol's own identity record, and CORE.md's repair path is `saipen rebind-home`, which is not an agent's call to make unilaterally on a host running other sessions.

IMP-004 [P2][PROJECT_VIOLATION][reproduced][ticket] limit_gauges strips English words out of a pool label that has already been translated
expected: a label is either translated as a whole or not word-stripped at all
actual: limit_gauges.py:1001 does clean_pool = pool.replace(" and ", " & ").replace(" models", "").replace(" Models", "") on a pool name that came from a translated data source. The substitution targets are English literals applied to a value whose spelling is locale-dependent, so it strips nothing in a translated locale and mangles the label in one that kept the words.
evidence: read of limit_gauges.py:1001 at HEAD. Cosmetic, and the same class as IMP-001: an English assumption surviving inside a translated surface.

Positive result, stated because the previous cycle's headline finding was the opposite: T-1362/T-1363's IMP-001 is FIXED. A clean detached worktree at b053bff reports problem_count 0, gate core, status CURRENT_PASS, where HEAD 6e64047 previously failed with 57 problems -- the protocol state that was untracked then is committed now.

Categories checked and found clean, so the negatives are on the record rather than assumed: persisted-setting round-trip (every write stores a raw value and every read-back compares against a raw constant -- _fill_mode at limit_overview.py:336 and limit_gauges.py:577 tests membership in ("remaining","used"), _style at limit_gauges.py:563 tests against _STYLES, and cmb_copy_from stores notification_key(...) as userData with only the label localized, so no translated value reaches disk); markup in a display position (the two remaining raw hex stylesheets at limit_overview.py:213 and :1282 are correctly untranslated); tr() calls with a non-literal first argument (an AST walk of all 280 calls in the four files found every first argument to be a string constant); missing or placeholder-drifted keys (every wrapped literal exists in all 33 packs with an identical {placeholder} set, and validate_saitranslate.py reports Missing from en.json: 0); limit_hover_card.py itself, which contains zero tr() calls and zero literals and is correctly out of scope; and limit_gauges.py:1371 _fmt_win, which holds raw English but has no production caller and is dead code.
