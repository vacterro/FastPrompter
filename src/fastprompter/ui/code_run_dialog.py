"""Smart Code Runner — review, execution and output UI (T-1456).

Qt-heavy half of the runner: the explicit-approval review dialog, the
QProcess-driven executor and the output dialog. The Qt-free half is
``core/code_detection.py`` and ``core/code_runners.py``.

No code executes without passing through ``CodeRunReviewDialog`` and the
user pressing Run. Nothing is ever executed on paste, hover, document load,
preview, or toolbar visibility change.
"""

from __future__ import annotations

import codecs
import time

from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from fastprompter.core.code_detection import (
    CodeCandidate,
    interpreter_key,
    language_display,
)
from fastprompter.core.code_runners import REGISTRY, stage_script
from fastprompter.core.translations import tr


class CodeRunReviewDialog(QDialog):
    """Explicit approval: shows the exact script and interpreter, then runs."""

    def __init__(self, main_win, candidates: list[CodeCandidate],
                 working_dir=None, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.candidates = candidates
        self.working_dir = working_dir
        self.chosen: CodeCandidate | None = None
        self.lang_override: str | None = None
        lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Run Code", lang))
        self.setMinimumSize(620, 520)
        self._build(lang, candidates)

    def _build(self, lang: str, candidates: list[CodeCandidate]) -> None:
        layout = QVBoxLayout(self)

        if len(candidates) > 1 or (candidates and candidates[0].ambiguous):
            layout.addWidget(QLabel(tr("Multiple runnable blocks were found. "
                                       "Choose one:", lang)))
            self.block_menu = QMenu(self)
            for index, candidate in enumerate(candidates):
                display = language_display(candidate.language)
                preview = " ".join(candidate.source.split())[:60]
                label = f"{index + 1}. [{display}] {preview}"
                self.block_menu.addAction(
                    label, lambda c=candidate: self._select(c))
            btn_choose = QPushButton(tr("Choose block...", lang))
            self.btn_choose = btn_choose
            btn_choose.setMenu(self.block_menu)
            layout.addWidget(btn_choose)
            self.chosen = None
            self.source_view = None
        else:
            self.chosen = candidates[0]
            self.source_view = self._source_edit(candidates[0].source)
            layout.addWidget(QLabel(tr("Exact code that will run:", lang)))
            layout.addWidget(self.source_view)

        info = QLabel()
        candidate = self.chosen or candidates[0]
        adapter = REGISTRY.get(_lang_key(candidate.language))
        display = language_display(candidate.language)
        exe_hint = adapter.exe_name if adapter else "unknown"
        scope = getattr(candidate, "reason", "")
        info.setText(tr("Language", lang) + f": {display}\n"
                    + tr("Interpreter", lang) + f": {exe_hint}\n"
                    + tr("Source scope", lang) + f": {scope}\n"
                    + tr("Working directory", lang) + f": {self.working_dir or 'temp'}\n"
                    + tr("Temporary script", lang) + ": yes")
        info.setWordWrap(True)
        layout.addWidget(info)

        warn = QLabel(tr("This runs with your current user permissions.", lang))
        warn.setWordWrap(True)
        layout.addWidget(warn)

        buttons = QHBoxLayout()
        self.btn_run = QPushButton(tr("Run", lang))
        self.btn_cancel = QPushButton(tr("Cancel", lang))
        self.btn_run.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        if len(candidates) > 1:
            self.btn_run.setEnabled(False)
            self.btn_run.clicked.disconnect()
            self.btn_run.clicked.connect(self._run_selected)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_run)
        buttons.addWidget(self.btn_cancel)
        layout.addLayout(buttons)

    def _select(self, candidate: CodeCandidate) -> None:
        self.chosen = candidate
        lang = getattr(self.main_win, "_current_lang", "EN")
        self.btn_choose.setText(
            tr("Block", lang)
            + f" {self.candidates.index(candidate) + 1} — "
            + f"{language_display(candidate.language)}")
        self.btn_run.setEnabled(True)
        self._source_view_refresh(candidate.source)
        self.lang_override = None

    def _source_edit(self, source: str) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setPlainText(source)
        view.setReadOnly(True)
        view.setFont(QFont("Consolas", 9))
        return view

    def _source_view_refresh(self, source: str) -> None:
        if getattr(self, "source_view", None) is not None:
            self.source_view.setPlainText(source)
        else:
            self.source_view = self._source_edit(source)
            self.layout().insertWidget(1, self.source_view)

    def _run_selected(self) -> None:
        if self.chosen is not None:
            self.accept()


def _lang_key(language: str) -> str:
    return interpreter_key(language)


class CodeRunOutputDialog(QDialog):
    """Runs the approved script via QProcess and shows truthful results."""

    def __init__(self, main_win, candidate: CodeCandidate, exe, args,
                 working_dir, source: str, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.candidate = candidate
        self.exe = exe
        self.args = list(args)
        self.working_dir = working_dir
        self.source = source
        self.process: QProcess | None = None
        self.staged = None
        self.start_time = 0.0
        self.elapsed = 0.0
        self._output_chunks = 0
        self._max_output_bytes = 512 * 1024
        self._timed_out = False
        self._encoding = "utf-8"
        self._decoder = None
        lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Running Code", lang))
        self.setMinimumSize(640, 480)
        self._build(lang)
        self._start()

    def _build(self, lang: str) -> None:
        layout = QVBoxLayout(self)

        self.status = QLabel(tr("Starting...", lang))
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        self.out_view = QPlainTextEdit()
        self.out_view.setReadOnly(True)
        self.out_view.setFont(QFont("Consolas", 9))
        layout.addWidget(self.out_view)

        buttons = QHBoxLayout()
        self.btn_stop = QPushButton(tr("Stop", lang))
        self.btn_stop.clicked.connect(self._stop)
        self.btn_copy = QPushButton(tr("Copy Output", lang))
        self.btn_copy.clicked.connect(self._copy_output)
        self.btn_close = QPushButton(tr("Close", lang))
        self.btn_close.clicked.connect(self._finish)
        self.btn_close.setEnabled(False)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_stop)
        buttons.addWidget(self.btn_copy)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    # -- execution ------------------------------------------------------------

    def _start(self) -> None:
        adapter_key = _lang_key(self.candidate.language)
        adapter = REGISTRY.get(adapter_key)
        if adapter is None:
            self.status.setText("No adapter for language")
            self._finish()
            return
        resolved = REGISTRY.resolve(adapter_key)
        if resolved is None:
            self.status.setText(
                tr("Interpreter not available", getattr(
                    self.main_win, "_current_lang", "EN")) + f": {adapter.exe_name}")
            self._finish()
            return
        exe, args_template = resolved
        self._encoding = adapter.encoding or "utf-8"
        try:
            self.staged = stage_script(self.candidate.source, adapter_key,
                                       working_dir=self.working_dir)
        except Exception as exc:
            self.status.setText(f"Staging failed: {exc}")
            self._finish()
            return
        argv = [str(a) for a in args_template] + [str(self.staged.path)]
        self.start_time = time.monotonic()

        self.process = QProcess(self)
        cwd = self.working_dir
        if cwd is not None:
            self.process.setWorkingDirectory(str(cwd))
        self.process.readyReadStandardOutput.connect(self._read_out)
        self.process.readyReadStandardError.connect(self._read_err)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        timeout_s = 30
        try:
            raw = self.main_win.data.get("code_run_timeout_seconds", "30")
            timeout_s = max(1, int(raw))
        except Exception:
            pass
        self._timer.start(timeout_s * 1000)
        self.process.start(str(exe), argv)

    def _read_out(self) -> None:
        if self.process:
            data = self.process.readAllStandardOutput()
            self._append(data, "stdout")

    def _read_err(self) -> None:
        if self.process:
            data = self.process.readAllStandardError()
            self._append(data, "stderr")

    def _append(self, data, tag: str) -> None:
        payload = bytes(data)
        if self._output_chunks + len(payload) > self._max_output_bytes:
            payload = payload[: max(0, self._max_output_bytes - self._output_chunks)]
            if not payload:
                return
        self._output_chunks += len(payload)
        if self._decoder is None:
            try:
                self._decoder = codecs.getincrementaldecoder(
                    self._encoding)(errors="replace")
            except LookupError:
                self._decoder = codecs.getincrementaldecoder(
                    "utf-8")(errors="replace")
        self.out_view.appendPlainText(self._decoder.decode(payload))

    def _flush_decoder(self) -> None:
        """Emit the tail held back across a chunk boundary."""
        if self._decoder is not None:
            tail = self._decoder.decode(b"", final=True)
            self._decoder = None
            if tail:
                self.out_view.appendPlainText(tail)

    def _on_finished(self, exit_code: int, _status) -> None:
        if self._timed_out:
            return
        self._timer.stop()
        self.elapsed = time.monotonic() - self.start_time
        lang = getattr(self.main_win, "_current_lang", "EN")
        if exit_code == 0:
            self.status.setText(
                tr("Success", lang) + f" — exit 0 in {self.elapsed:.2f}s")
        else:
            self.status.setText(
                tr("Failed", lang) + f" — exit {exit_code} in {self.elapsed:.2f}s")
        self._cleanup_process()

    def _on_error(self, error) -> None:
        self._timer.stop()
        lang = getattr(self.main_win, "_current_lang", "EN")
        self.status.setText(tr("Process error", lang) + f": {error}")
        self._cleanup_process()

    def _on_timeout(self) -> None:
        self._timed_out = True
        lang = getattr(self.main_win, "_current_lang", "EN")
        self._terminate_process()
        self.status.setText(
            tr("Timed out", lang) + f" after {self._timer.interval() // 1000}s")
        self._cleanup_process()

    def _stop(self) -> None:
        self._timed_out = True
        self._timer.stop()
        self._terminate_process()
        self.elapsed = time.monotonic() - self.start_time
        self.status.setText(
            tr("Stopped by user", getattr(self.main_win, "_current_lang", "EN"))
            + f" after {self.elapsed:.2f}s")
        self._cleanup_process()

    def _terminate_process(self) -> None:
        """Kill the child and reap it, so cleanup can unlink the staged file.

        Without the wait, Windows can refuse to delete a script whose
        interpreter was just killed, and the timeout path used to leave the
        child running entirely.
        """
        if self.process is None:
            return
        self.process.kill()
        self.process.waitForFinished(3000)

    def _cleanup_process(self) -> None:
        self._flush_decoder()
        if self.process is not None:
            self.process.readyReadStandardOutput.disconnect()
            self.process.readyReadStandardError.disconnect()
            self.process.finished.disconnect()
            self.process.errorOccurred.disconnect()
            self.process = None
        if self.staged is not None:
            self.staged.cleanup()
            self.staged = None
        self._timer.stop()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.btn_stop.setEnabled(False)
        self.btn_close.setEnabled(True)

    def _copy_output(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.out_view.toPlainText())

    def _finish(self) -> None:
        self._cleanup_process()
        self.accept()
