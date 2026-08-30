"""Scrollable unified-diff viewer overlay.

Parses ``git diff`` output into structured hunks and renders them
with color-coded added/removed lines inside the curses TUI.
"""
from __future__ import annotations

import curses
from typing import List, Tuple

from .render import safe_render

# Color pair IDs (must not collide with other modules)
_PAIR_DIFF_ADD = 20
_PAIR_DIFF_DEL = 21
_PAIR_DIFF_HUNK = 22
_PAIR_DIFF_HDR = 23


def init_diff_colors() -> None:
    """Register color pairs for the diff viewer."""
    if not curses.has_colors():
        return
    try:
        from . import settings
        from . import themes
        name = settings.get_active_theme_name()
        if name:
            diff = themes.THEMES[themes.resolve_theme_id(name)].get("diff", {})
            fg, bg = themes._resolve(*diff.get("add", (2, -1)))
            curses.init_pair(_PAIR_DIFF_ADD, fg, bg)
            fg, bg = themes._resolve(*diff.get("del", (1, -1)))
            curses.init_pair(_PAIR_DIFF_DEL, fg, bg)
            fg, bg = themes._resolve(*diff.get("hunk", (6, -1)))
            curses.init_pair(_PAIR_DIFF_HUNK, fg, bg)
            fg, bg = themes._resolve(*diff.get("header", (3, -1)))
            curses.init_pair(_PAIR_DIFF_HDR, fg, bg)
            return
    except Exception:
        pass
    curses.init_pair(_PAIR_DIFF_ADD, curses.COLOR_GREEN, -1)
    curses.init_pair(_PAIR_DIFF_DEL, curses.COLOR_RED, -1)
    curses.init_pair(_PAIR_DIFF_HUNK, curses.COLOR_CYAN, -1)
    curses.init_pair(_PAIR_DIFF_HDR, curses.COLOR_YELLOW, -1)


class DiffViewer:
    """State for the scrollable diff overlay."""

    def __init__(self, diff_text: str = "", title: str = "") -> None:
        self.diff_text: str = diff_text
        self.title: str = title
        self.lines: List[Tuple[str, str]] = []  # (type, text) — type in hunk/header/add/del/context
        self.scroll_y: int = 0

    def load(self, diff_text: str, title: str = "") -> None:
        self.diff_text = diff_text
        self.title = title
        self.scroll_y = 0
        self.lines = self._parse(diff_text)

    def scroll(self, dy: int) -> None:
        max_scroll = max(0, len(self.lines) - 1)
        self.scroll_y = max(0, min(self.scroll_y + dy, max_scroll))

    def page_down(self, page_height: int) -> None:
        self.scroll(page_height)

    def page_up(self, page_height: int) -> None:
        self.scroll(-page_height)

    def home(self) -> None:
        self.scroll_y = 0

    def end(self, page_height: int) -> None:
        self.scroll_y = max(0, len(self.lines) - page_height)

    @staticmethod
    def _parse(diff_text: str) -> List[Tuple[str, str]]:
        """Parse unified diff into (type, text) pairs."""
        result: List[Tuple[str, str]] = []
        for line in diff_text.split("\n"):
            if line.startswith("diff --git") or line.startswith("index "):
                result.append(("header", line))
            elif line.startswith("@@"):
                result.append(("hunk", line))
            elif line.startswith("new file") or line.startswith("deleted file"):
                result.append(("header", line))
            elif line.startswith("---") or line.startswith("+++"):
                result.append(("header", line))
            elif line.startswith("+"):
                result.append(("add", line))
            elif line.startswith("-"):
                result.append(("del", line))
            else:
                result.append(("context", line))
        if result and result[-1] == ("context", ""):
            result.pop()
        return result


def draw_diff_overlay(
    stdscr,
    viewer: DiffViewer,
    height: int,
    width: int,
) -> None:
    """Draw the diff viewer as a full-screen overlay."""
    stdscr.erase()

    # Title bar
    title_text = f" {viewer.title} " if viewer.title else " Diff "
    try:
        stdscr.addstr(0, 0, title_text.center(width)[:width],
                      curses.A_REVERSE | curses.A_BOLD)
    except curses.error:
        pass

    # Hint bar at bottom
    hints = " \u2191\u2193:scroll  d/Space:pgdn  u/PgUp:pgup  g/G:home/end  q/Esc:close"
    try:
        stdscr.addstr(height - 1, 0, hints[:width], curses.A_DIM)
    except curses.error:
        pass

    # Diff content area: rows 1 to height-2
    content_height = max(1, height - 2)
    max_scroll = max(0, len(viewer.lines) - content_height)

    for row in range(content_height):
        line_idx = viewer.scroll_y + row
        if line_idx >= len(viewer.lines):
            break
        ltype, text = viewer.lines[line_idx]
        # Truncate to fit
        display = text[:width]

        if ltype == "add":
            attr = curses.color_pair(_PAIR_DIFF_ADD) | curses.A_BOLD
        elif ltype == "del":
            attr = curses.color_pair(_PAIR_DIFF_DEL)
        elif ltype == "hunk":
            attr = curses.color_pair(_PAIR_DIFF_HUNK) | curses.A_BOLD
        elif ltype == "header":
            attr = curses.color_pair(_PAIR_DIFF_HDR) | curses.A_BOLD
        else:
            attr = 0

        try:
            stdscr.addstr(row + 1, 0, safe_render(display), attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass

    # Scroll indicator
    if len(viewer.lines) > content_height:
        pct = viewer.scroll_y / max(1, max_scroll)
        bar_row = 1 + int(pct * (content_height - 1))
        try:
            stdscr.addstr(min(bar_row + 1, height - 2), width - 1, "\u2588", curses.A_DIM)
        except curses.error:
            pass

    stdscr.refresh()


def diff_viewer_key(viewer: DiffViewer, key: str | int, page_height: int) -> bool:
    """Handle a keypress in the diff viewer. Returns True if consumed."""
    if key == "q" or key == "\x1b":
        return False  # signal close
    elif key in ("down", curses.KEY_DOWN):
        viewer.scroll(1)
    elif key in ("up", curses.KEY_UP):
        viewer.scroll(-1)
    elif key in ("d", " ", "\x06"):  # d / Space / Ctrl-F
        viewer.page_down(page_height)
    elif key in ("u", "\x12"):  # u / Ctrl-R
        viewer.page_up(page_height)
    elif key in (curses.KEY_NPAGE,):
        viewer.page_down(page_height)
    elif key in (curses.KEY_PPAGE,):
        viewer.page_up(page_height)
    elif key == "g":
        viewer.home()
    elif key == "G":
        viewer.end(page_height)
    else:
        return True  # consumed but no action
    return True
