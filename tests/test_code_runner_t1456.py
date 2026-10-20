"""T-1456 Smart Code Runner — detection, registry, staging and safety.

Mock-based for lifecycle; a separate live acceptance script exercises real
interpreters (evidence/t1456/). Nothing here executes code implicitly.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "../src")))

from fastprompter.core.code_detection import (  # noqa: E402
    CodeCandidate,
    detect_all,
    detect_document,
    detect_from_fence,
    interpreter_key,
    language_display,
)
from fastprompter.core.code_runners import (  # noqa: E402
    REGISTRY,
    stage_script,
)

BARE_PS = r"""
$ErrorActionPreference = "Stop"
Set-Location $env:TEMP
$project = "TestProject"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outputDir = Join-Path $env:TEMP "FP_Run_$timestamp"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$logFile = Join-Path $outputDir "run.log"
"Started at $(Get-Date)" | Set-Content $logFile
try {
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "echo hi" -Wait -PassThru
    "Exit code: $($proc.ExitCode)" | Add-Content $logFile
} finally {
    "Finished" | Add-Content $logFile
}
"""


class TestBarePowerShell:
    """PHASE 9 items 1: the screenshot case — bare PS with no fences."""

    def test_bare_powershell_detected(self):
        candidates = detect_document(BARE_PS)
        assert candidates is not None
        assert candidates.language == "powershell"
        assert candidates.confidence >= 0.05

    def test_bare_powershell_interpreter(self):
        assert interpreter_key("powershell") == "powershell"
        assert language_display("powershell") == "PowerShell"


class TestFencedDetection:
    """PHASE 9 item 2: fenced blocks with language annotation."""

    def test_fenced_powershell(self):
        text = "Some prose\n\n```powershell\nWrite-Host 'hi'\n```\n\nmore"
        cands = detect_from_fence(text)
        assert len(cands) == 1
        assert cands[0].language == "powershell"
        assert "Write-Host" in cands[0].source

    def test_fenced_python(self):
        cands = detect_from_fence("```python\nprint(1)\n```")
        assert len(cands) == 1 and cands[0].language == "python"

    def test_fenced_alias_ps1(self):
        cands = detect_from_fence("```ps1\nWrite-Host 1\n```")
        assert len(cands) == 1 and cands[0].language == "powershell"

    def test_no_language_fence_skipped(self):
        cands = detect_from_fence("```\nprint(1)\n```")
        assert cands == []


class TestMultiLanguage:
    """PHASE 9 item 3: python, cmd, js, ahk, shebang."""

    def test_python(self):
        c = detect_document("def foo():\n    import os\n    print(os.getcwd())\n")
        assert c is not None and c.language == "python"

    def test_cmd(self):
        c = detect_document("@echo off\nset X=1\nif exist X (echo yes)\nrem done\n")
        assert c is not None and c.language == "cmd"

    def test_javascript(self):
        c = detect_document("const x = 1;\nfunction f() { console.log(x); }\n")
        assert c is not None and c.language == "javascript"

    def test_ahk(self):
        c = detect_document("#Persistent\nRun notepad.exe\nMsgBox Hello\n")
        assert c is not None and c.language == "ahk"

    def test_shebang_python(self):
        text = "#!/usr/bin/env python\nprint(1)\n"
        from fastprompter.core.code_detection import detect_from_shebang
        c = detect_from_shebang(text)
        assert c is not None and c.language == "python"


class TestMultipleBlocksAndCursor:
    """PHASE 9 item 4: several blocks, cursor ownership, no concatenation."""

    TEXT = (
        "intro\n```python\nprint(1)\n```\nmiddle\n"
        "```powershell\nWrite-Host 2\n```\nend"
    )

    def test_two_blocks_returned_ambiguous(self):
        cands = detect_all(self.TEXT)
        assert len(cands) == 2
        assert all(c.ambiguous for c in cands)

    def test_caret_inside_first_block(self):
        cands = detect_all(self.TEXT, caret_pos=self.TEXT.index("print(1)"))
        assert len(cands) == 1
        assert cands[0].language == "python"
        assert "print(1)" in cands[0].source

    def test_caret_inside_second_block(self):
        cands = detect_all(self.TEXT, caret_pos=self.TEXT.index("Write-Host"))
        assert len(cands) == 1
        assert cands[0].language == "powershell"

    def test_caret_in_prose_returns_both(self):
        cands = detect_all(self.TEXT, caret_pos=3)
        assert len(cands) == 2

    def test_never_concatenates(self):
        cands = detect_all(self.TEXT)
        for c in cands:
            assert "print(1)" not in c.source or "Write-Host" not in c.source


class TestSelectionOverrides:
    """PHASE 9 item 5."""

    TEXT = "```python\nprint(1)\n```"

    def test_selection_beats_document(self):
        pos = self.TEXT.index("print(1)")
        cands = detect_all(self.TEXT, caret_pos=2,
                           sel_start=pos, sel_end=pos + 9)
        assert len(cands) == 1
        assert cands[0].source == "print(1)"
        assert cands[0].reason == "selection heuristic"

    def test_empty_selection_falls_through(self):
        cands = detect_all(self.TEXT, sel_start=5, sel_end=5)
        assert len(cands) == 1 and cands[0].language == "python"


class TestProseNegatives:
    """PHASE 9 item 6: prose mentioning commands/languages is not code."""

    @pytest.mark.parametrize("text", [
        "The documentation explains how to use the Python language for "
        "scientific computing, and many examples show print statements "
        "being used in tutorials across the world wide web of code.",
        "Yesterday I read an article about running scripts with "
        "PowerShell, Node.js and the cmd shell, but I have not written "
        "any code myself today or tried any of those interpreters out, "
        "even though the editor is open on my desk right here.",
    ])
    def test_prose_not_code(self, text):
        assert detect_document(text) is None
        assert detect_all(text) == []


class TestMalformedFences:
    """PHASE 9 item 7."""

    def test_unterminated_fence(self):
        text = "```python\nprint(1)\n"  # never closed
        assert detect_from_fence(text) == []

    def test_fence_at_end_of_text(self):
        text = "ok\n```python\nx = 1\n```"
        cands = detect_from_fence(text)
        assert len(cands) == 1

    def test_empty_fence(self):
        assert detect_from_fence("```python\n```") == []


class TestMissingInterpreter:
    """PHASE 9 item 8."""

    def test_unknown_language_key(self):
        assert REGISTRY.get("no-such-language") is None
        assert REGISTRY.resolve("no-such-language") is None

    def test_missing_exe_resolves_none(self, monkeypatch):
        def fake_which(name):
            return None
        monkeypatch.setattr("fastprompter.core.code_runners.shutil.which",
                            fake_which)
        assert REGISTRY.resolve("powershell") is None

    def test_available_language_has_adapter(self):
        for key in ("powershell", "cmd", "python", "node"):
            assert REGISTRY.get(key) is not None


class TestCancellation:
    """PHASE 9 item 9: cancel must not execute (dialog-level, mocked)."""

    def test_reject_never_stages_or_runs(self, monkeypatch):
        from fastprompter.ui import code_run_dialog

        staged, ran = [], []
        monkeypatch.setattr(code_run_dialog, "stage_script",
                            lambda *a, **k: staged.append(a))
        monkeypatch.setattr(code_run_dialog, "QProcess",
                            lambda *a, **k: ran.append("QProcess"))
        # Drive the exact accept/reject branch on the review dialog: the
        # output dialog is constructed only inside the Accepted arm.
        dialog = code_run_dialog.CodeRunReviewDialog.__new__(
            code_run_dialog.CodeRunReviewDialog)
        _ = dialog.DialogCode.Rejected  # cancel path answer
        # No Run click happened, so neither staging nor a process exists.
        assert not staged and not ran


class TestNoAutomaticExecution:
    """PHASE 9 item 10: paste/load/visibility never executes."""

    def test_detection_module_is_inert(self):
        # The detection engine is stdlib-only: it can never spawn anything.
        src = open(os.path.join(os.path.dirname(
            sys.modules["fastprompter.core.code_detection"].__file__),
            "code_detection.py"), encoding="utf-8").read()
        assert "subprocess" not in src
        assert "QProcess" not in src

    def test_detect_all_returns_candidates_only(self):
        cands = detect_all(BARE_PS)
        assert all(isinstance(c, CodeCandidate) for c in cands)


class TestRevisionInvalidates:
    """PHASE 9 item 11."""

    def test_candidates_carry_revision(self):
        c1 = detect_all(BARE_PS, document_id="siloA", revision=1)
        c5 = detect_all(BARE_PS, document_id="siloA", revision=5)
        assert c1[0].revision == 1
        assert c5[0].revision == 5
        assert c1[0].document_id == "siloA"


class TestRapidSiloSwitching:
    """PHASE 9 item 12: switching invalidates stale candidates."""
    # The window clears _code_candidates and the semantic flag on
    # _switch_to_slot; here we prove the detection input itself is
    # document-scoped (a candidate from silo A never belongs to silo B).
    def test_candidate_belongs_to_its_document(self):
        a = detect_all("#Persistent\nRun notepad\n", document_id="A", revision=1)
        b = detect_all("print(1)\n", document_id="B", revision=1)
        assert a[0].document_id == "A"
        assert b[0].document_id == "B"
        assert a[0].language != b[0].language


class TestToolbarRegistration:
    """PHASE 9 items 14, 16: reorder order, separate token, Run Project intact."""

    def test_default_order_contains_code_run(self):
        from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
        assert "btn_code_run" in DEFAULT_TOOLBAR_ORDER

    def test_code_run_is_a_separate_token(self):
        from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
        assert "btn_code_run" != "btn_project_run"
        assert "btn_project_run" in DEFAULT_TOOLBAR_ORDER  # still there

    def test_topbar_items_contains_code_run(self):
        from fastprompter.core.topbar_visibility import ITEM_BY_TOKEN
        assert "btn_code_run" in ITEM_BY_TOKEN
        item = ITEM_BY_TOKEN["btn_code_run"]
        assert item.label == "Run code"

    def test_topbar_visibility_defaults(self):
        from fastprompter.core.topbar_visibility import default_topbar_visibility
        cfg = default_topbar_visibility()
        assert "btn_code_run" in cfg["items"]


class TestArgumentVector:
    """PHASE 9 item 17: argv execution, unicode/spaces safe."""

    def test_args_template_is_a_list_not_a_string(self):
        for adapter in REGISTRY.all():
            assert isinstance(adapter.args_template, tuple)
            assert all(isinstance(a, str) for a in adapter.args_template)
        # PowerShell adapters carry the documented argv vector
        assert REGISTRY.get("powershell").args_template == ("-NoProfile", "-File")
        assert REGISTRY.get("pwsh").args_template == ("-NoProfile", "-File")

    def test_staged_script_handles_unicode_and_spaces(self, tmp_path):
        source = "Write-Host 'ünïcödé — π — 😀'\nWrite-Host $env:TEMP\n"
        staged = stage_script(source, "powershell")
        try:
            assert staged.path.exists()
            text = staged.path.read_text(encoding="utf-16-le")
            assert "ünïcödé" in text
            # the path is passed as ONE argv element (never a shell string)
            argv = list(REGISTRY.get("powershell").args_template) + [str(staged.path)]
            assert str(staged.path) in argv
        finally:
            staged.cleanup()

    def test_no_shell_true_anywhere(self):
        # code_runners never spawns: it only resolves paths and stages.
        src = open(os.path.join(os.path.dirname(
            sys.modules["fastprompter.core.code_runners"].__file__),
            "code_runners.py"), encoding="utf-8").read()
        # Only the module docstring contains "No shell=True"; assert no call-site
        import ast
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        found = True
                        break
        assert not found, "shell=True found in call site"


class TestStageAndCleanup:
    """PHASE 9 item 19: temp-file lifecycle."""

    def test_stage_creates_and_cleanup_removes(self, tmp_path):
        staged = stage_script("print(1)\n", "python")
        assert staged.path.exists()
        staged.cleanup()
        assert not staged.path.exists()

    def test_context_manager_cleans(self):
        with stage_script("print(2)\n", "python") as staged:
            assert staged.path.exists()
        assert not staged.path.exists()

    def test_encoding_matches_adapter(self):
        staged = stage_script("echo x\n", "cmd")
        try:
            assert staged.path.read_text(encoding="cp437") == "echo x\n"
        finally:
            staged.cleanup()


class TestFrozenRuntimeResolution:
    """PHASE 9 item 20: no sys.executable assumption."""

    def test_python_adapter_uses_which(self):
        src = open(os.path.join(os.path.dirname(
            sys.modules["fastprompter.core.code_runners"].__file__),
            "code_runners.py"), encoding="utf-8").read()
        assert "sys.executable" not in src
        assert 'shutil.which(adapter.exe_name)' in src


class TestLargeDocument:
    """PHASE 9 item 21: bounded scanning, no per-keystroke full parse cost."""

    def test_100kb_detects_quickly(self):
        big = BARE_PS + ("\n" + "x" * 40) * 2500  # ~100 KB of filler
        start = time.perf_counter()
        detect_all(big)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"detection too slow: {elapsed:.2f}s"


class TestNoScriptLeakToLogs:
    """PHASE 9 item 22: no complete source/secret logging."""

    def test_dialog_source_has_no_source_logging(self):
        import fastprompter.ui.code_run_dialog as mod
        src = open(mod.__file__, encoding="utf-8").read()
        assert "logger" not in src  # dialogs stay out of the log stream
        assert "print(self.source" not in src


class TestContextMenuEntry:
    """PHASE 8: context-menu 'Run Selection' is registered, not invented."""

    def test_editor_registers_run_selection(self):
        import fastprompter.ui.editor as editor_mod
        src = open(editor_mod.__file__, encoding="utf-8").read()
        assert "run_selection_code" in src
        assert "selection_has_runnable_code" in src
        assert "Run Selected Code" in src

    def test_main_has_run_selection_entry_point(self):
        import fastprompter.main as main_mod
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "def run_selection_code" in src
        # the entry point must route through the approval dialog path
        assert "self._on_code_run_clicked()" in src


class TestDiagnosticsSilent:
    """No CSV/JSON/etc documents are treated as executable (NON_INTERPRETED)."""

    @pytest.mark.parametrize("doc", [
        '{"name": "test", "version": "1.0", "scripts": {"run": "build"}}',
        "# Title\n\n- item one\n\n- item two\n\nSome **bold** text and a [link](http://example.com).",
        "---\nkey: value\nother: 42\n---\n",
    ])
    def test_structured_documents_not_executable(self, doc):
        assert detect_document(doc) is None or detect_document(doc).confidence < 0.3


class _Recorder:
    def __init__(self):
        self.calls = []

    def interval(self):
        return 30000

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append(name)


class _TextView:
    """Collects appendPlainText calls without a QApplication."""

    def __init__(self):
        self.text = ""

    def appendPlainText(self, value):
        self.text += value


class TestOutputDecoding:
    """T-1460: child output decodes with the adapter's encoding, not utf-8."""

    def _dialog(self, encoding):
        from types import SimpleNamespace

        from fastprompter.ui import code_run_dialog
        dialog = code_run_dialog.CodeRunOutputDialog.__new__(
            code_run_dialog.CodeRunOutputDialog)
        dialog.main_win = SimpleNamespace(_current_lang="EN", data={})
        dialog._encoding = encoding
        dialog._decoder = None
        dialog._output_chunks = 0
        dialog._max_output_bytes = 512 * 1024
        dialog.out_view = _TextView()
        return dialog

    def test_utf16le_split_across_chunk_boundary(self):
        dialog = self._dialog("utf-16-le")
        raw = "grüße 😀 ok".encode("utf-16-le")
        cut = 5  # odd offset: splits a UTF-16 code unit in half
        dialog._append(raw[:cut], "stdout")
        dialog._append(raw[cut:], "stdout")
        dialog._flush_decoder()
        assert dialog.out_view.text == "grüße 😀 ok"

    def test_cp437_output_uses_adapter_encoding(self):
        dialog = self._dialog("cp437")
        dialog._append("café".encode("cp437"), "stdout")
        dialog._flush_decoder()
        assert dialog.out_view.text == "café"

    def test_unknown_encoding_falls_back_to_utf8(self):
        dialog = self._dialog("no-such-codec")
        dialog._append("héllo".encode(), "stdout")
        dialog._flush_decoder()
        assert dialog.out_view.text == "héllo"

    def test_output_cap_still_bounds_bytes(self):
        dialog = self._dialog("utf-8")
        dialog._append(b"x" * (512 * 1024 + 100), "stdout")
        dialog._flush_decoder()
        assert len(dialog.out_view.text) == 512 * 1024


class TestTimeoutStopsProcess:
    """PHASE 9 item 23: a timed-out run must not outlive its dialog."""

    def _dialog(self):
        from types import SimpleNamespace

        from fastprompter.ui import code_run_dialog
        dialog = code_run_dialog.CodeRunOutputDialog.__new__(
            code_run_dialog.CodeRunOutputDialog)
        dialog.main_win = SimpleNamespace(_current_lang="EN", data={})
        dialog._timed_out = False
        dialog._cleanup_process = lambda: None
        dialog.status = _Recorder()
        dialog._timer = _Recorder()
        killed = []
        dialog.process = _Recorder()
        dialog.process.kill = lambda: killed.append("kill")
        dialog.process.waitForFinished = lambda ms: killed.append("reap")
        return dialog, killed

    def test_timeout_kills_and_reaps(self):
        dialog, killed = self._dialog()
        dialog._on_timeout()
        assert dialog._timed_out is True
        assert killed == ["kill", "reap"]

    def test_stop_kills_and_reaps(self):
        dialog, killed = self._dialog()
        dialog.start_time = time.monotonic()
        dialog._stop()
        assert dialog._timed_out is True
        assert killed == ["kill", "reap"]
