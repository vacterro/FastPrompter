# T-1257 closure evidence

## Source state (unchanged, not redesigned)

`src/fastprompter/ui/editor.py:772-774`

```python
color, _name = MARK_PALETTE.get(mark, MARK_PALETTE[1])
painter.setPen(QPen(QColor("#000000"), 1))
painter.setBrush(QColor(color))
```

The persistent palette STRING is converted at the Qt boundary. No raw string
reaches `QPainter.setBrush`.

## Why the defect was invisible as a test failure

PyQt6 does NOT propagate an exception raised inside a C++ virtual (here
`LineNumberArea.paintEvent`). It routes it to `sys.excepthook` and then calls
`qFatal()`. Controlled probes on this tree:

* fixed code, real `repaint()` -> 0 exceptions reached `sys.excepthook`;
* defect reintroduced (`painter.setBrush(MARK_PALETTE[1][0])`), custom hook ->
  exactly one
  `TypeError: arguments did not match any overloaded call: setBrush(self, brush: QBrush|QColor|Qt.GlobalColor|int|QGradient): argument 1 has unexpected type 'str'`
  and the process survived only because the hook was replaced;
* same defect with the DEFAULT hook, child process -> terminated with
  `-1073740791` (0xC0000409), no test failure reported.

That is why a `QColor(...).isValid()` style test is worthless here: the defect
never becomes an assertion, it becomes a dead process.

## Regression added

`tests/test_line_mark_toggle.py` (cases N / O / P / P2 / Q). Each drives the
REAL `LineNumberArea.paintEvent` through `repaint()` under a captured
`sys.excepthook`, then reads the painted gutter back as pixels:

| case | proves |
|------|--------|
| N | all five `MARK_PALETTE` ids paint, each lands as its exact hex; text and stored id unchanged |
| O | empty hovered slot: centre stays gutter background (`Qt.BrushStyle.NoBrush`), outline drawn |
| P | queue stripes render `#6aa9ff` (queued) / `#46b98a` (sent) |
| P2 | a mark and a stripe coexist in one paint pass |
| Q | palette hexes and persistent ids unchanged |

`python -m pytest tests/test_line_mark_toggle.py -q` -> **18 passed**.

Editor regression wave (`test_line_mark_toggle`, `test_editor_delete_sounds`,
`test_editor_document_cache`, `test_editor_pinned_selection`,
`test_editor_snapshot_sentinel`, `test_line_drag_autoscroll`,
`test_markdown_highlighter`, `test_markdown_highlighter_wave`)
-> **128 passed**.

## Full-suite diagnostic

| field | value |
|-------|-------|
| command | `python -m pytest tests/` |
| cwd | `V:\___VAC\__K\__CODE\_PY\_FastPrompter` |
| start (UTC) | 2026-09-13T20:59:12.6217009Z |
| end (UTC) | 2026-09-13T21:31:00.7950136Z |
| exit code | 3 |
| stdout | `run1.stdout` (14498 bytes, complete) |
| stderr | `run1.stderr` (10931 bytes, complete) |
| pytest summary | NOT REACHED - abnormal termination |

### EXPLANATION OF EXIT CODE 3

Exit 3 is **not** pytest's INTERNALERROR. `run1.stderr` line 1 is

```
Fatal Python error: Aborted
```

i.e. the CRT `abort()`, which on Windows leaves the process with exit code 3.
The faulthandler main-thread frame (`run1.stderr:81-82`) is

```
Current thread 0x0000450c (most recent call first):
  File "V:\___VAC\__K\__CODE\_PY\_FastPrompter\tests\test_timer_fire.py", line 296 in test_test_notification_job_is_registered_and_fires
```

`test_timer_fire.py:296` is `QTest.qWait(50)` - a NESTED Qt event loop. The
abort happens inside that loop, driven by objects leaked by earlier modules,
not by any gutter paint. The archived attempt
`.saipen/t1257-full-pytest-2.log:107-108` names the SAME line, so the crash
site is stable across runs and predates this work.

`tests\test_line_mark_toggle.py ..................` appears at 31% of the same
run: every line-mark test passes inside the full suite.

**Classification: T-1264 / T-1260 (leaked cross-module Qt state), NOT T-1257.**

### Failures visible before the abort

| file | count | ticket |
|------|-------|--------|
| test_fastprompter_night_upgrade.py | 1 | T-1262 (stale `sound_volume` whitelist) |
| test_new_empty_silos.py | 1 | T-1260 (order-dependent) |
| test_perf005_scaled_cache.py | 1 | T-1260 (order-dependent) |
| test_shutdown_ownership.py | 1 | T-1260 (order-dependent) |
| test_suite_exit_contract.py | 3 | environmental, see below |
| test_t1227_silo_integrity.py | 1 | T-1261 (Stage B) |
| test_timer_dialog_wave.py | 1 | T-1260 (passes standalone) |

`test_suite_exit_contract` spawns child pytest runs. The child dies during
collection with

```
FileNotFoundError: [WinError 2] The system cannot find the file specified:
'V:\_TEMP_\limisaw_codexsession_fake_704bdffd539b41cda8ffce1cc5243f5e'
<frozen genericpath>:100: FileNotFoundError
```

Reproduced independently with an unrelated stale entry
(`V:/_TEMP_/saipen-conformance-index-9jgqbb7s`): pytest's collection compares
temp-dir candidates with `os.path.samefile` and raises on entries that have
already been deleted. `V:\_TEMP_` on this workstation holds thousands of stale
`limisaw_*` directories. Environmental, outside the repository, not in scope
here.
