"""Ephemeral per-document selection interaction undo/redo history (T-1426).

Enables user-intent undo where meaningful selection transitions
(selection created, selection collapsed, selection altered) can be
reversed with Ctrl+Z and reapplied with Ctrl+Y without modifying
document text or interfering with native text or data undo chronology.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CursorSelectionState:
    anchor: int
    position: int
    scroll: int = 0

    @property
    def has_selection(self) -> bool:
        return self.anchor != self.position

    @property
    def selection_start(self) -> int:
        return min(self.anchor, self.position)

    @property
    def selection_end(self) -> int:
        return max(self.anchor, self.position)

    @property
    def is_forward(self) -> bool:
        return self.position >= self.anchor


@dataclass(frozen=True)
class SelectionInteractionRecord:
    before: CursorSelectionState
    after: CursorSelectionState
    doc_id: int
    doc_generation: int
    text_length: int
    text_undo_steps: int
    action_seq: int


def is_meaningful_selection_transition(
    before: CursorSelectionState,
    after: CursorSelectionState,
) -> bool:
    """Predicate for recording selection transitions.

    Records:
    1. no-selection -> selection
    2. selection -> no-selection
    3. selection A -> materially different selection B

    Does NOT record:
    - ordinary caret navigation (no selection in both before and after)
    - identical before/after states
    """
    if before.anchor == after.anchor and before.position == after.position:
        return False
    if not before.has_selection and not after.has_selection:
        return False
    return True


class DocumentInteractionHistory:
    def __init__(self, doc_id: int, generation: int = 0):
        self.doc_id = doc_id
        self.generation = generation
        self.undo_stack: list[SelectionInteractionRecord] = []
        self.redo_stack: list[SelectionInteractionRecord] = []

    def push(self, record: SelectionInteractionRecord) -> None:
        self.undo_stack.append(record)
        self.redo_stack.clear()

    def update_top_after(self, new_after: CursorSelectionState) -> bool:
        if not self.undo_stack:
            return False
        top = self.undo_stack[-1]
        if not is_meaningful_selection_transition(top.before, new_after):
            self.undo_stack.pop()
            return True
        updated = SelectionInteractionRecord(
            before=top.before,
            after=new_after,
            doc_id=top.doc_id,
            doc_generation=top.doc_generation,
            text_length=top.text_length,
            text_undo_steps=top.text_undo_steps,
            action_seq=top.action_seq,
        )
        self.undo_stack[-1] = updated
        return True

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def peek_undo(self) -> Optional[SelectionInteractionRecord]:
        return self.undo_stack[-1] if self.undo_stack else None

    def pop_undo(self) -> Optional[SelectionInteractionRecord]:
        return self.undo_stack.pop() if self.undo_stack else None

    def peek_redo(self) -> Optional[SelectionInteractionRecord]:
        return self.redo_stack[-1] if self.redo_stack else None

    def pop_redo(self) -> Optional[SelectionInteractionRecord]:
        return self.redo_stack.pop() if self.redo_stack else None

    def push_redo(self, record: SelectionInteractionRecord) -> None:
        self.redo_stack.append(record)

    def clear_redo(self) -> None:
        self.redo_stack.clear()

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()


def get_document_interaction_history(doc) -> Optional[DocumentInteractionHistory]:
    if doc is None:
        return None
    history = getattr(doc, "_fastprompter_interaction_history", None)
    if history is None:
        gen = getattr(doc, "_fastprompter_generation", 0)
        history = DocumentInteractionHistory(doc_id=id(doc), generation=gen)
        doc._fastprompter_interaction_history = history
    return history
