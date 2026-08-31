from types import SimpleNamespace
from unittest.mock import MagicMock

from PyQt6.QtGui import QTextDocument

from fastprompter.ui.editor import VaultTextEdit


def _main_window():
    return SimpleNamespace(
        data={
            "show_line_numbers": "False",
            "code_auto_gutter": "False",
            "line_marks": "False",
        },
        highlighter=None,
        _LARGE_DOC_THRESHOLD=500_000,
    )


def test_unchanged_document_attach_reuses_feature_metadata(qapp):
    editor = VaultTextEdit(_main_window())
    doc = QTextDocument()
    doc.setPlainText("[ ] task\n```python\npass\n```")
    editor.set_active_document(doc)
    assert doc._fastprompter_has_checkbox is True
    assert doc._fastprompter_has_code is True

    editor._refresh_checkbox_flag = MagicMock(
        wraps=editor._refresh_checkbox_flag)
    editor.set_active_document(doc)
    editor._refresh_checkbox_flag.assert_not_called()


def test_many_short_lines_get_only_bounded_attach_scan(qapp):
    main = _main_window()
    main._LARGE_DOC_BLOCK_THRESHOLD = 2_000
    editor = VaultTextEdit(main)
    doc = QTextDocument()
    doc.setPlainText("\n".join(["short"] * 2_500 + ["[ ] late checkbox"]))
    editor.set_active_document(doc)
    # The marker is beyond the first bounded chunk. Navigation stays cheap;
    # later edits reconcile their own changed range incrementally.
    assert editor._doc_has_checkbox is False
    assert doc._fastprompter_feature_revision == doc.revision()
