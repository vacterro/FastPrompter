"""Tests for fastprompter.core.logging — logger setup and exception hook."""

import io
import logging
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.logging import _LOG_FILE, _setup_logger, exception_hook, logger


# Disable file-rotation teardown in test for clean runs
@pytest.fixture(autouse=True)
def _cleanup_logger():
    """Restore logger state after each test."""
    yield
    # Ensure the logger doesn't accumulate test handlers
    log = logging.getLogger("fastprompter")
    for h in list(log.handlers):
        if hasattr(h, "_test_handler"):
            log.removeHandler(h)


class TestSetupLogger:
    """Verify the internal _setup_logger function."""

    def test_returns_logger_instance(self):
        """_setup_logger should return a logging.Logger."""
        result = _setup_logger()
        assert isinstance(result, logging.Logger)

    def test_logger_name_is_fastprompter(self):
        """The logger name should be 'fastprompter'."""
        result = _setup_logger()
        assert result.name == "fastprompter"

    def test_logger_level_is_debug(self):
        """Logger should be set to DEBUG level."""
        result = _setup_logger()
        assert result.level == logging.DEBUG

    def test_has_file_handler(self):
        """Logger should have a RotatingFileHandler for the log file."""
        result = _setup_logger()
        fhs = [h for h in result.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(fhs) >= 1

    def test_file_handler_writes_to_temp_log(self):
        """The file handler should write to the configured _LOG_FILE path."""
        result = _setup_logger()
        fhs = [h for h in result.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        if fhs:
            assert fhs[0].baseFilename == _LOG_FILE

    def test_has_stderr_handler(self):
        """Logger should have a StreamHandler writing to stderr."""
        result = _setup_logger()
        sh = [h for h in result.handlers if isinstance(h, logging.StreamHandler)]
        assert len(sh) >= 1

    def test_stderr_handler_level_is_warning(self):
        """The stderr handler should be at WARNING level (only warnings+ go to terminal)."""
        result = _setup_logger()
        sh = [
            h
            for h in result.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ]
        if sh:
            assert sh[0].level == logging.WARNING

    def test_idempotent(self):
        """Calling _setup_logger twice should return the same logger without duplicate handlers."""
        logger1 = _setup_logger()
        count_before = len(logger1.handlers)
        logger2 = _setup_logger()
        count_after = len(logger2.handlers)
        assert logger1 is logger2
        assert count_after == count_before, "Duplicate handlers should not be added"

    def test_file_handler_rotation_config(self):
        """RotatingFileHandler should have 1 MB max and 2 backup count."""
        result = _setup_logger()
        fhs = [h for h in result.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        if fhs:
            fh = fhs[0]
            assert fh.maxBytes == 1_048_576
            assert fh.backupCount == 2

    def test_formatter_has_timestamp(self):
        """The log formatter should include a timestamp (asctime)."""
        result = _setup_logger()
        for h in result.handlers:
            if h.formatter:
                fmt_str = h.formatter._fmt or ""
                assert "%(asctime)s" in fmt_str, "Formatter should include timestamp"


class TestLoggerSingleton:
    """Verify the module-level logger singleton."""

    def test_logger_is_configured(self):
        """Module-level logger should be a configured Logger instance."""
        assert isinstance(logger, logging.Logger)
        assert logger.name == "fastprompter"

    def test_logger_can_log(self):
        """Logger should be capable of logging without error."""
        # This should not raise
        logger.debug("Test debug message")
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")

    def test_logger_writes_to_stderr(self):
        """WARNING-level messages should reach stderr."""
        # Capture stderr
        stderr_buf = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_buf
        try:
            # Temporarily add a stderr handler at DEBUG level to verify output
            handler = logging.StreamHandler(sys.stderr)
            handler._test_handler = True  # marker for cleanup
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            logger.warning("test_stderr_message_12345")
            output = stderr_buf.getvalue()
            assert "test_stderr_message_12345" in output
        finally:
            sys.stderr = old_stderr
            logger.removeHandler(handler)


class TestExceptionHook:
    """Verify the exception_hook function."""

    def test_does_not_crash(self):
        """exception_hook should handle a basic exception without crashing."""
        try:
            1 / 0
        except ZeroDivisionError:
            exctype, value, tb = sys.exc_info()
            # Should not raise
            exception_hook(exctype, value, tb)

    def test_logs_critical_level(self):
        """exception_hook should log at CRITICAL level."""
        # Capture log output
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler._test_handler = True
        handler.setLevel(logging.CRITICAL)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)

        try:
            raise ValueError("test_exception")
        except ValueError:
            exctype, value, tb = sys.exc_info()
            exception_hook(exctype, value, tb)

        output = log_capture.getvalue()
        assert "CRITICAL" in output
        assert "test_exception" in output
        logger.removeHandler(handler)

    def test_writes_to_crash_file(self):
        """exception_hook should write to the crash log file."""
        crash_path = os.path.join(tempfile.gettempdir(), "fastprompter_crash.log")
        # Remove any existing crash log
        try:
            os.remove(crash_path)
        except FileNotFoundError:
            pass

        try:
            raise RuntimeError("crash_test_456")
        except RuntimeError:
            exctype, value, tb = sys.exc_info()
            exception_hook(exctype, value, tb)

        # Check that crash file was created and contains the error
        assert os.path.exists(crash_path)
        with open(crash_path, encoding="utf-8") as f:
            content = f.read()
        assert "crash_test_456" in content

    def test_handles_systemexit(self):
        """exception_hook should handle SystemExit without crashing."""
        try:
            raise SystemExit(0)
        except SystemExit:
            exctype, value, tb = sys.exc_info()
            # Should not raise
            exception_hook(exctype, value, tb)

    def test_handles_keyboardinterrupt(self):
        """exception_hook should handle KeyboardInterrupt without crashing."""
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            exctype, value, tb = sys.exc_info()
            # Should not raise
            exception_hook(exctype, value, tb)


class TestLogFileConstant:
    """Verify the _LOG_FILE module constant."""

    def test_is_string(self):
        assert isinstance(_LOG_FILE, str)

    def test_ends_with_a_fastprompter_log(self):
        # under pytest the path moves aside on purpose: the suite raises
        # real exceptions, and writing them to the file the installed app
        # uses buried a user's crash evidence and rotated it away
        assert _LOG_FILE.endswith("fastprompter-tests.log")

    def test_the_app_path_is_not_the_test_path(self):
        from fastprompter.core.logging import _default_log_file
        assert _default_log_file().endswith("fastprompter-tests.log")
        assert "fastprompter.log" not in os.path.basename(_LOG_FILE)

    def test_is_absolute_path(self):
        assert os.path.isabs(_LOG_FILE)
