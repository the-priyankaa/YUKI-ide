"""Dashboard Extensions overlay — discovery-only listing.

The list is built from extension *filenames/metadata* without importing any
extension module, so starting the editor never loads third-party code and a
broken extension can never break this screen (spec: lazy discovery).

Empty state copies the documented message verbatim:

    No extensions available at the moment

``Ctrl+1`` returns to YUKI; the TUI owns that translation.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

import curses

from .extensions.loader import discover, extension_dirs
from .render import safe_render


class ExtensionsView:
    """Explicit, deterministic state for the dashboard Extensions overlay."""

    def __init__(self, cwd: Optional[str] = None) -> None:
        self.active = False
        self.entries: List[Tuple[str, str]] = []  # (stem, absolute path)
        self.selected = 0
        self.scroll = 0
        self.cwd = cwd

    def open(self) -> None:
        """(Re)discover extensions without importing any of them."""
        self.entries = [
            (path.stem, str(path.resolve()))
            for path in discover(self.cwd)
        ]
        self.selected = 0
        self.scroll = 0
        self.active = True

    def close(self) -> None:
        self.active = False

    def directory_count(self) -> int:
        return len(extension_dirs(self.cwd))

    def move(self, dy: int) -> None:
        if self.entries:
            self.selected = max(0, min(self.selected + dy, len(self.entries) - 1))

    def visible_entries(self, view_h: int) -> List[int]:
        """Row indices for a *view_h*-row window, selection always visible."""
        n = len(self.entries)
        if view_h <= 0:
            self.scroll = 0
            return []
        self.scroll = max(0, min(self.scroll, max(0, n - view_h)))
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + view_h:
            self.scroll = self.selected - view_h + 1
        return list(range(self.scroll, min(n, self.scroll + view_h)))


EMPTY_STATE = "No extensions available at the moment"


def draw(stdscr, view: ExtensionsView, height: int, width: int) -> None:
    """Paint the centered bordered Extensions overlay in one pass.

    Uses a real curses sub-window + ``.box()`` (same technique as the New
    File dialog fix) instead of hand-built border strings, so every row
    is guaranteed to share the same width and the box draws as a true
    overlay on top of the dashboard already on screen — nothing outside
    the window's own rectangle is touched, and the TUI refreshes once
    after this returns.
    """
    inner_w = max(46, min(78, width * 72 // 100))
    inner_w = min(inner_w, width - 2)
    n = len(view.entries)
    view_h = max(1, min(max(4, height - 10), max(1, n or 1)))
    box_h = view_h + 6
    win_h = min(box_h, height)
    win_w = min(inner_w + 2, width)
    top = max(0, (height - win_h) // 2)
    left = max(0, (width - win_w) // 2)

    try:
        win = stdscr.derwin(win_h, win_w, top, left)
    except curses.error:
        return
    win.erase()
    win.box()

    content_w = max(0, win_w - 2)

    def put(row, col, text, attr=0):
        try:
            win.addstr(row, col, safe_render(text)[: max(0, content_w - col + 1)], attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass

    def row_text(row, text, attr=0):
        put(row, 1, (text + " " * content_w)[:content_w], attr)

    title = " EXTENSIONS "
    put(0, max(1, (win_w - len(title)) // 2), title, curses.A_REVERSE)

    dirs = extension_dirs(view.cwd)
    shown = ", ".join(str(d) for d in dirs) or "no search paths"
    if len(shown) > content_w - 8:
        shown = "..." + shown[-(content_w - 11):]
    row_text(1, f" Search: {shown}", curses.A_DIM)

    sep_row = 2
    try:
        win.hline(sep_row, 1, curses.ACS_HLINE, content_w)
        win.addch(sep_row, 0, curses.ACS_LTEE)
        win.addch(sep_row, win_w - 1, curses.ACS_RTEE)
    except curses.error:
        pass

    if not view.entries:
        row_text(3, " " + EMPTY_STATE, curses.A_DIM)
        row_text(4, " Place .py files in an extension directory and reopen.",
                 curses.A_DIM)
        row_text(5, " \u2191/\u2193 n/a  Esc back  Ctrl+1 YUKI", curses.A_DIM)
    else:
        indices = view.visible_entries(view_h)
        for slot, idx in enumerate(indices):
            stem, path = view.entries[idx]
            sel = idx == view.selected
            attr = curses.A_REVERSE if sel else 0
            short = path
            if len(short) > content_w - 10:
                short = "..." + short[-(content_w - 13):]
            display = f"{'\u25b6 ' if sel else '   '}{stem:<20} {short}"
            row_text(3 + slot, display, attr)
        row_text(3 + view_h,
                 f" \u2191/\u2193 select  {len(view.entries)} discovered  "
                 "Esc back  Ctrl+1 YUKI", curses.A_DIM)
    win.noutrefresh()