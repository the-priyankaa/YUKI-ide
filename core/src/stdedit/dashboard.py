"""Responsive YUKI welcome dashboard.

The dashboard is presentation-only: actions are returned to the existing TUI
so file opening, settings, and editor behavior continue to use the project's
real implementations.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass


import curses

from . import recent
from .render import safe_render



GREEN_PAIR = 30
GREEN_DIM_PAIR = 31
GREEN_REVERSE_PAIR = 32
GREEN_BRIGHT_PAIR = 33

LOGO = [
    r"██╗   ██╗██╗   ██╗██╗  ██╗██╗",
    r"╚██╗ ██╔╝██║   ██║██║ ██╔╝██║",
    r" ╚████╔╝ ██║   ██║█████╔╝ ██║",
    r"  ╚██╔╝  ██║   ██║██╔═██╗ ██║",
    r"   ██║   ╚██████╔╝██║  ██╗██║",
    r"   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝",
]

ACTIONS = [
    ("⌕", "F", "Find File", "Search and open a file"),
    ("▣", "D", "Open Folder", "Search and open a folder"),
    ("▤", "O", "Open Project", "Browse a folder in the file tree"),
    ("□", "N", "New File", "Pick a folder, type a name, create it"),
    ("◷", "R", "Recent Files", "Open recently edited files"),
    ("⇶", "E", "Extensions", "List available extensions"),
    ("↻", "S", "Restore Session", "Open the most recent file"),
    ("⚙", "C", "Settings", "Edit configuration"),
    ("?", "H", "Help", "Keyboard reference (F1)"),
    ("⇥", "Q", "Quit", "Exit Yuki"),
]

MAX_ACTIONS = len(ACTIONS)

TIPS = (
    "Stay lazy. Let Yuki\ndo the heavy lifting.",
    "Small tools. Fast feedback.\nNo ceremony.",
    "Open a file, make the change,\nsave it, move on.",
)


@dataclass(frozen=True)
class Rect:
    y: int
    x: int
    h: int
    w: int


def init_colors() -> None:
    """Create dashboard-specific green pairs when the terminal supports color."""
    if not curses.has_colors():
        return
    try:
        max_pairs = getattr(curses, "COLOR_PAIRS", 0)
        if max_pairs <= GREEN_PAIR:
            return
        curses.init_pair(GREEN_PAIR, curses.COLOR_GREEN, -1)
        curses.init_pair(GREEN_DIM_PAIR, curses.COLOR_GREEN, -1)
        curses.init_pair(GREEN_REVERSE_PAIR, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(GREEN_BRIGHT_PAIR, curses.COLOR_GREEN, -1)
    except curses.error:
        pass


def cp(pair: int, attr: int = 0) -> int:
    try:
        return curses.color_pair(pair) | attr
    except curses.error:
        return attr


def safe_addstr(stdscr, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
    if y < 0 or x < 0:
        return
    try:
        if width is not None:
            text = text[:max(0, width)]
        stdscr.addstr(y, x, safe_render(text), attr)
    except (curses.error, ValueError, UnicodeEncodeError):
        pass


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _box(stdscr, r: Rect, title: str = "", attr: int = 0) -> None:
    if r.h < 2 or r.w < 2:
        return
    a = attr or cp(GREEN_PAIR)
    try:
        stdscr.addch(r.y, r.x, "┌", a)
        stdscr.addch(r.y, r.x + r.w - 1, "┐", a)
        stdscr.addch(r.y + r.h - 1, r.x, "└", a)
        stdscr.addch(r.y + r.h - 1, r.x + r.w - 1, "┘", a)
        stdscr.hline(r.y, r.x + 1, curses.ACS_HLINE, max(0, r.w - 2), a)
        stdscr.hline(r.y + r.h - 1, r.x + 1, curses.ACS_HLINE, max(0, r.w - 2), a)
        stdscr.vline(r.y + 1, r.x, curses.ACS_VLINE, max(0, r.h - 2), a)
        stdscr.vline(r.y + 1, r.x + r.w - 1, curses.ACS_VLINE, max(0, r.h - 2), a)
    except curses.error:
        return
    if title and r.w > len(title) + 4:
        label = f" {title} "
        safe_addstr(stdscr, r.y, r.x + 2, label, cp(GREEN_BRIGHT_PAIR, curses.A_BOLD))


def layout(height: int, width: int) -> dict[str, Rect]:
    """Calculate a dashboard layout that stays inside the terminal."""
    h = max(1, height)
    w = max(1, width)

    # Ultra-small terminals: keep a usable single action strip rather than
    # trying to squeeze the full dashboard into impossible dimensions.
    if h < 14 or w < 48:
        hero = Rect(2 if h >= 3 else 0, 1, 2 if h >= 4 else 1, max(1, w - 2))
        action_y = min(h - 3, hero.y + hero.h + 1)
        action_h = max(1, h - action_y - 2)
        return {
            "action": Rect(action_y, 1, action_h, max(1, w - 2)),
            "status": Rect(0, 0, 0, 0),
            "quick": Rect(0, 0, 0, 0),
            "recent": Rect(0, 0, 0, 0),
            "shortcuts": Rect(0, 0, 0, 0),
            "tip": Rect(0, 0, 0, 0),
            "bottom": Rect(max(0, h - 2), 0, min(2, h), w),
            "hero": hero,
        }

    top = 2
    header_h = 3
    hero_y = top + header_h
    hero_h = 7 if h >= 28 else 5 if h >= 20 else 3
    body_y = hero_y + hero_h + 1
    body_h = max(4, h - body_y - 9)

    if w >= 105:
        left_w = int(w * 0.62)
        status_x = left_w + 3
        right_w = max(1, w - status_x - 1)
        status_h = max(7, body_h // 2)
        quick_h = max(4, body_h - status_h - 1)
        action = Rect(body_y, 2, body_h, left_w)
        status = Rect(body_y, status_x, status_h, right_w)
        quick = Rect(body_y + status_h + 1, status_x, quick_h, right_w)
    elif w >= 75:
        right_w = max(24, w // 4)
        left_w = max(30, w - right_w - 3)
        status_x = left_w + 3
        right_w = max(1, w - status_x - 1)
        action = Rect(body_y, 2, body_h, left_w)
        status = Rect(body_y, status_x, body_h, right_w)
        quick = Rect(0, 0, 0, 0)
    else:
        action_h = max(4, body_h // 2 + 1)
        action = Rect(body_y, 2, action_h, max(18, w - 4))
        status = Rect(body_y + action_h + 1, 2, max(3, body_h - action_h - 1), max(18, w - 4))
        quick = Rect(0, 0, 0, 0)

    bottom_y = min(h - 4, max(body_y + body_h + 1, h - 7))
    bottom_h = max(3, h - bottom_y - 2)
    if w >= 105:
        gap = 2
        col = max(20, (w - 4 - gap * 2) // 3)
        recent_box = Rect(bottom_y, 2, bottom_h, col)
        shortcuts = Rect(bottom_y, 2 + col + gap, bottom_h, col)
        tip_x = 2 + 2 * (col + gap)
        tip = Rect(bottom_y, tip_x, bottom_h, max(20, w - tip_x - 1))
    elif w >= 75:
        half = max(30, (w - 5) // 2)
        recent_box = Rect(bottom_y, 2, bottom_h, half)
        shortcuts = Rect(bottom_y, 3 + half, bottom_h, max(30, w - 4 - half))
        tip = Rect(0, 0, 0, 0)
    else:
        recent_box = Rect(0, 0, 0, 0)
        shortcuts = Rect(0, 0, 0, 0)
        tip = Rect(0, 0, 0, 0)
    return {
        "action": action,
        "status": status,
        "quick": quick,
        "recent": recent_box,
        "shortcuts": shortcuts,
        "tip": tip,
        "bottom": Rect(h - 2, 0, 2, w),
        "hero": Rect(hero_y, 2, hero_h, w - 4),
    }


def _draw_header(stdscr, height: int, width: int, uptime: float, ram_label: str) -> None:
    a = cp(GREEN_PAIR, curses.A_BOLD)
    dim = cp(GREEN_DIM_PAIR)
    line = "─" * max(0, width - 4)
    safe_addstr(stdscr, 0, 2, "YUKI PERSONAL TERMINAL", a, max(0, width - 4))
    right = f"SYS: OK  |  {ram_label}  |  {time.strftime('%H:%M:%S')}"
    if width > len(right) + 25:
        safe_addstr(stdscr, 0, width - len(right) - 2, right, a)
    safe_addstr(stdscr, 1, 2, line, dim)


def _draw_hero(stdscr, r: Rect, width: int) -> None:
    if r.h <= 0 or r.w <= 0:
        return
    logo_w = min(72, r.w // 2 + 8)
    info_x = r.x + logo_w + 4
    safe_addstr(stdscr, r.y, max(3, r.x + (logo_w - 4) // 3), "YUKI", cp(GREEN_BRIGHT_PAIR, curses.A_BOLD))
    if r.h >= 5 and width >= 75:
        # Use the large logo only when there is enough room for it.
        for i, line in enumerate(LOGO[: r.h]):
            safe_addstr(stdscr, r.y + i, r.x + 3, line, cp(GREEN_BRIGHT_PAIR, curses.A_BOLD), logo_w - 4)
        if info_x < width - 20:
            _box(stdscr, Rect(r.y + 1, info_x, min(6, r.h - 1), width - info_x - 3))
            safe_addstr(stdscr, r.y + 2, info_x + 2, "YUKI v0.1.0", cp(GREEN_BRIGHT_PAIR, curses.A_BOLD))
            safe_addstr(stdscr, r.y + 3, info_x + 2, "A terminal native IDE", cp(GREEN_PAIR), width - info_x - 5)
            safe_addstr(stdscr, r.y + 4, info_x + 2, "Fast. Lightweight. Focused.", cp(GREEN_PAIR), width - info_x - 5)
            if r.h >= 6:
                safe_addstr(stdscr, r.y + 5, info_x + 2, "All systems nominal.", cp(GREEN_PAIR), width - info_x - 5)
    else:
        centered = "TERMINAL IDE  —  Fast. Lightweight. Focused."
        safe_addstr(stdscr, r.y + max(0, r.h // 2), r.x + max(0, (r.w - len(centered)) // 2), centered, cp(GREEN_PAIR, curses.A_BOLD), r.w)


def _draw_actions(stdscr, r: Rect, selected: int) -> None:
    _box(stdscr, r, "TERMINAL IDE")
    if r.h < 4:
        return
    rows = r.h - 2
    step = 1 if rows >= len(ACTIONS) else max(1, rows // len(ACTIONS))
    for i, (icon, key, label, desc) in enumerate(ACTIONS):
        y = r.y + 1 + i * step
        if y >= r.y + r.h - 1:
            break
        sel = i == selected
        attr = cp(GREEN_REVERSE_PAIR, curses.A_BOLD) if sel else cp(GREEN_PAIR)
        marker = f"[{key}]"
        left = f" {icon:<4} {marker:<5} {label:<18}"
        safe_addstr(stdscr, y, r.x + 2, left, attr, max(0, r.w - 4))
        if r.w >= 60:
            safe_addstr(stdscr, y, r.x + min(40, r.w // 2), desc, cp(GREEN_PAIR), max(0, r.w - (min(40, r.w // 2) + 2)))


def _draw_status(stdscr, r: Rect, ram_label: str, startup_ms: float, project: str = "none") -> None:
    _box(stdscr, r, "SYSTEM STATUS")
    if r.h < 4:
        return
    rows = [
        ("Python", f"{__import__('platform').python_version()}"),
        ("Yuki", "0.1.0"),
        ("Core", "stdlib"),
        ("Plugins", "opt-in"),
        ("Startup", f"{startup_ms:.1f}ms"),
        ("RAM", ram_label.replace("RAM ", "")),
    ]
    for i, (k, v) in enumerate(rows[: max(0, r.h - 2)]):
        safe_addstr(stdscr, r.y + 1 + i, r.x + 2, f"{k:<10} {v}", cp(GREEN_PAIR), r.w - 4)


def _draw_quick(stdscr, r: Rect, project: str = "none") -> None:
    if r.h <= 0 or r.w <= 0:
        return
    _box(stdscr, r, "QUICK INFO")
    vals = [("Session", "ready"), ("Project", _truncate(project, max(8, r.w - 14))), ("Git Branch", "-"), ("Diagnostics", "0")]
    for i, (k, v) in enumerate(vals):
        if r.y + 1 + i >= r.y + r.h - 1:
            break
        safe_addstr(stdscr, r.y + 1 + i, r.x + 2, f"{k:<12}{v}", cp(GREEN_PAIR), r.w - 4)


def _draw_recent(stdscr, r: Rect) -> None:
    if r.h <= 0:
        return
    _box(stdscr, r, "RECENT PROJECTS")
    entries = [p for p in recent.get_recent() if os.path.exists(p)][:5]
    if not entries:
        entries = ["No recent files"]
    for i, path in enumerate(entries):
        safe_addstr(stdscr, r.y + 1 + i, r.x + 2, _truncate(path, r.w - 4), cp(GREEN_PAIR), r.w - 4)


def _draw_shortcuts(stdscr, r: Rect) -> None:
    if r.h <= 0:
        return
    _box(stdscr, r, "SHORTCUTS")
    rows = ["<Enter>/<Space> : Activate", "F        : Find File", "D        : Open Folder", "O        : Open Project", "N        : New File", "R        : Recent Files", "E        : Extensions", "S        : Restore Session", "C        : Settings", "H / F1   : Help", "Q        : Quit", "Ctrl+1    : YUKI"]
    for i, line in enumerate(rows[: max(0, r.h - 2)]):
        safe_addstr(stdscr, r.y + 1 + i, r.x + 2, _truncate(line, r.w - 4), cp(GREEN_PAIR), r.w - 4)


def _draw_tip(stdscr, r: Rect) -> None:
    if r.h <= 0:
        return
    _box(stdscr, r, "TIP OF THE DAY")
    tip = TIPS[int(time.time() / 30) % len(TIPS)].splitlines()
    start = r.y + max(1, (r.h - len(tip)) // 2)
    for i, line in enumerate(tip):
        x = r.x + max(1, (r.w - len(line)) // 2)
        safe_addstr(stdscr, start + i, x, line, cp(GREEN_PAIR), r.w - (x - r.x) - 1)


def draw(stdscr, selected: int, uptime: float, ram_label: str, project: str = "none",
         message: str = "", refresh: bool = True) -> None:
    """Draw the dashboard at the current terminal dimensions.

    ``refresh`` defaults to True so single-call wrappers keep working.  Set
    it to False when the caller composes another overlay on top of this frame
    and issues the ``stdscr.refresh()`` once at the end (one-frame rendering
    — never paint the dashboard and an overlay with two separate refresh()es,
    which causes a visible camera-shutter flicker).
    """
    height, width = stdscr.getmaxyx()
    init_colors()
    stdscr.erase()
    _draw_header(stdscr, height, width, uptime, ram_label)
    boxes = layout(height, width)
    _draw_hero(stdscr, boxes["hero"], width)
    _draw_actions(stdscr, boxes["action"], selected)
    _draw_status(stdscr, boxes["status"], ram_label, uptime * 1000.0, project)
    _draw_quick(stdscr, boxes["quick"], project)
    _draw_recent(stdscr, boxes["recent"])
    _draw_shortcuts(stdscr, boxes["shortcuts"])
    _draw_tip(stdscr, boxes["tip"])
    status = f"NORMAL   no project   •   Enter selects   •   ↑↓ navigate   •   Q quits"
    if message:
        status = f"{message}   •   {status}"
    safe_addstr(stdscr, height - 1, 2, _truncate(status, max(0, width - 4)), cp(GREEN_REVERSE_PAIR, curses.A_BOLD))
    if refresh:
        stdscr.refresh()


def action_count() -> int:
    return len(ACTIONS)


def action_key(index: int) -> str:
    return ACTIONS[index][1]
