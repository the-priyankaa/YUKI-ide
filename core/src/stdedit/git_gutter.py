"""Inline git gutter markers for the editor.

Computes and caches diff hunks per file, provides line-level markers
for the editor gutter (+ added, ~ modified, - deleted).
"""
from __future__ import annotations

import curses
import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import git
from . import git as git_module


@dataclass
class GutterMark:
    """A single gutter marker for a line."""
    line: int           # 1-indexed line number in current buffer
    type: str           # "added", "modified", "deleted"
    hunk: Optional[git.GitHunk] = None


class GitGutter:
    """Manages inline git diff markers for a file.

    Computes diff hunks in background thread, caches results,
    and provides line->marker mapping for gutter rendering.
    """

    def __init__(self, root_dir: str, filepath: str) -> None:
        self.root_dir = root_dir
        self.filepath = filepath
        self.marks: dict[int, GutterMark] = {}  # line -> mark
        self.hunks: list[git.GitHunk] = []
        self._lock = threading.Lock()
        self._compute_thread: Optional[threading.Thread] = None
        self._dirty = True
        self._last_mtime = 0.0

    def maybe_refresh(self, buf_text: str) -> bool:
        """Refresh if file changed. Returns True if marks updated."""
        try:
            import os
            full_path = os.path.join(self.root_dir, self.filepath)
            mtime = os.path.getmtime(full_path)
            if mtime == self._last_mtime and not self._dirty:
                return False
            self._last_mtime = mtime
        except OSError:
            pass

        self._dirty = False
        self._compute_async(buf_text)
        return True

    def _compute_async(self, buf_text: str) -> None:
        """Compute diff in background thread."""
        if self._compute_thread and self._compute_thread.is_alive():
            return

        def compute():
            try:
                hunks = git.get_diff_hunks(self.root_dir, self.filepath, staged=False)
                staged_hunks = git.get_diff_hunks(self.root_dir, self.filepath, staged=True)
                marks = self._hunks_to_marks(hunks, staged_hunks, buf_text)
                with self._lock:
                    self.hunks = hunks + staged_hunks
                    self.marks = marks
            except Exception:
                pass

        self._compute_thread = threading.Thread(target=compute, daemon=True)
        self._compute_thread.start()

    def _hunks_to_marks(self, hunks: list[git.GitHunk], staged_hunks: list[git.GitHunk],
                        buf_text: str) -> dict[int, GutterMark]:
        """Convert hunks to line->mark mapping."""
        marks: dict[int, GutterMark] = {}

        # Unstaged hunks (worktree changes)
        for hunk in hunks:
            start, end = hunk.line_range()
            for line in range(start, end + 1):
                # Determine type from hunk lines
                mark_type = "modified"
                for hline in hunk.lines:
                    if hline.startswith("+") and not hline.startswith("+++"):
                        mark_type = "added"
                        break
                    elif hline.startswith("-") and not hline.startswith("---"):
                        mark_type = "deleted"
                marks[line] = GutterMark(line, mark_type, hunk)

        # Staged hunks - override or combine
        for hunk in staged_hunks:
            start, end = hunk.line_range()
            for line in range(start, end + 1):
                if line in marks:
                    # Both staged and unstaged - show as staged (green)
                    marks[line] = GutterMark(line, "added", hunk)
                else:
                    marks[line] = GutterMark(line, "added", hunk)

        return marks

    def get_mark(self, line: int) -> Optional[GutterMark]:
        """Get gutter mark for a line (1-indexed)."""
        with self._lock:
            return self.marks.get(line)

    def get_hunk_at_line(self, line: int) -> Optional[git.GitHunk]:
        """Get the hunk containing a line."""
        with self._lock:
            for hunk in self.hunks:
                if hunk.contains_line(line):
                    return hunk
        return None

    def get_all_hunks(self) -> list[git.GitHunk]:
        with self._lock:
            return list(self.hunks)

    def invalidate(self) -> None:
        """Force refresh on next maybe_refresh."""
        self._dirty = True


# Global gutter cache per (root_dir, filepath)
_gutter_cache: dict[tuple[str, str], GitGutter] = {}
_cache_lock = threading.Lock()


def get_gutter(root_dir: str, filepath: str) -> GitGutter:
    """Get or create GitGutter for a file."""
    key = (os.path.abspath(root_dir), filepath)
    with _cache_lock:
        if key not in _gutter_cache:
            _gutter_cache[key] = GitGutter(root_dir, filepath)
        return _gutter_cache[key]


def clear_gutter_cache(root_dir: str | None = None) -> None:
    """Clear gutter cache for a root dir or all."""
    with _cache_lock:
        if root_dir is None:
            _gutter_cache.clear()
        else:
            root_abs = os.path.abspath(root_dir)
            keys_to_del = [k for k in _gutter_cache if k[0] == root_abs]
            for k in keys_to_del:
                del _gutter_cache[k]


# Color pairs for gutter markers
_PAIR_GUTTER_ADDED = 50
_PAIR_GUTTER_MODIFIED = 51
_PAIR_GUTTER_DELETED = 52


def init_gutter_colors() -> None:
    """Initialize color pairs for gutter markers."""
    if not curses.has_colors():
        return
    try:
        from . import settings
        from . import themes
        name = settings.get_active_theme_name()
        if name:
            gutter = themes.THEMES[themes.resolve_theme_id(name)].get("gutter", {})
            fg, bg = themes._resolve(*gutter.get("added", (2, -1)))
            curses.init_pair(_PAIR_GUTTER_ADDED, fg, bg)
            fg, bg = themes._resolve(*gutter.get("modified", (3, -1)))
            curses.init_pair(_PAIR_GUTTER_MODIFIED, fg, bg)
            fg, bg = themes._resolve(*gutter.get("deleted", (1, -1)))
            curses.init_pair(_PAIR_GUTTER_DELETED, fg, bg)
            return
    except Exception:
        pass
    curses.init_pair(_PAIR_GUTTER_ADDED, curses.COLOR_GREEN, -1)
    curses.init_pair(_PAIR_GUTTER_MODIFIED, curses.COLOR_YELLOW, -1)
    curses.init_pair(_PAIR_GUTTER_DELETED, curses.COLOR_RED, -1)


def draw_gutter_mark(stdscr, row: int, col: int, mark: GutterMark) -> None:
    """Draw a single gutter marker at position."""
    char = ""
    attr = 0
    if mark.type == "added":
        char = "+"
        attr = curses.color_pair(_PAIR_GUTTER_ADDED) | curses.A_BOLD
    elif mark.type == "modified":
        char = "~"
        attr = curses.color_pair(_PAIR_GUTTER_MODIFIED) | curses.A_BOLD
    elif mark.type == "deleted":
        char = "-"
        attr = curses.color_pair(_PAIR_GUTTER_DELETED) | curses.A_BOLD
    if char:
        try:
            stdscr.addstr(row, col, char, attr)
        except curses.error:
            pass