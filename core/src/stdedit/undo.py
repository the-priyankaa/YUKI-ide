"""Memory-bounded snapshot undo/redo.

Snapshots keep immutable line references rather than copying every string.
History is bounded by both count and a conservative memory estimate so large
files cannot retain hundreds of whole-buffer snapshots indefinitely.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import List, Optional, Tuple

MAX_HISTORY = 500
DEFAULT_HISTORY_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class Snapshot:
    lines: Tuple[str, ...]
    cursor_x: int
    cursor_y: int

    @property
    def estimated_bytes(self) -> int:
        # Conservative estimate. Each snapshot retains a tuple of references
        # plus the strings that may have become unique in that edit history.
        # Counting strings conservatively is intentional: RAM safety is more
        # important than maximizing the number of undo steps for huge files.
        return sys.getsizeof(self.lines) + sum(sys.getsizeof(s) for s in self.lines) + 32


class UndoManager:
    def __init__(
        self,
        max_history: int = MAX_HISTORY,
        max_bytes: int = DEFAULT_HISTORY_BYTES,
    ) -> None:
        self._undo_stack: List[Snapshot] = []
        self._redo_stack: List[Snapshot] = []
        self._max_history = max(0, max_history)
        self._max_bytes = max(0, max_bytes)
        self._history_bytes = 0

    @property
    def history_bytes(self) -> int:
        return self._history_bytes

    @property
    def history_count(self) -> int:
        return len(self._undo_stack) + len(self._redo_stack)

    def _clear_redo(self) -> None:
        self._redo_stack.clear()
        self._history_bytes = sum(s.estimated_bytes for s in self._undo_stack)

    def _trim(self) -> None:
        while (
            self._undo_stack or self._redo_stack
        ) and (
            len(self._undo_stack) + len(self._redo_stack) > self._max_history
            or self._history_bytes > self._max_bytes
        ):
            # Preserve recent redo information when possible, but discard the
            # oldest undo state first because it is least useful.
            if self._undo_stack:
                oldest = self._undo_stack.pop(0)
            else:
                oldest = self._redo_stack.pop(0)
            self._history_bytes -= oldest.estimated_bytes

    def checkpoint(self, lines: List[str], cursor_x: int, cursor_y: int) -> None:
        """Record current state as an undo point and clear redo history."""
        snap = Snapshot(tuple(lines), cursor_x, cursor_y)
        if self._undo_stack and self._undo_stack[-1].lines == snap.lines:
            return

        self._clear_redo()

        # If one snapshot alone exceeds the budget, don't retain it. This is
        # what prevents a 100 MB+ document from immediately allocating another
        # 100 MB history snapshot. Editing continues normally without history.
        if snap.estimated_bytes > self._max_bytes:
            self._undo_stack.clear()
            self._history_bytes = 0
            return

        self._undo_stack.append(snap)
        self._history_bytes += snap.estimated_bytes
        self._trim()

    def undo(self, current_lines: List[str], cursor_x: int, cursor_y: int) -> Optional[Snapshot]:
        if not self._undo_stack:
            return None
        current = Snapshot(tuple(current_lines), cursor_x, cursor_y)
        prev = self._undo_stack.pop()
        self._history_bytes -= prev.estimated_bytes
        self._redo_stack.append(current)
        self._history_bytes += current.estimated_bytes
        self._trim()
        return prev

    def redo(self, current_lines: List[str], cursor_x: int, cursor_y: int) -> Optional[Snapshot]:
        if not self._redo_stack:
            return None
        current = Snapshot(tuple(current_lines), cursor_x, cursor_y)
        nxt = self._redo_stack.pop()
        self._history_bytes -= nxt.estimated_bytes
        self._undo_stack.append(current)
        self._history_bytes += current.estimated_bytes
        self._trim()
        return nxt
