"""
tui.py — curses front end. OWNER: Person A.

Phase 1 targets (per plan):
  - curses init, raw mode, color pairs, resize loop, minimal keymap
Phase 2 targets:
  - line numbers, status bar (file/lang/position), word-wrap toggle
Phase 3 targets:
  - multiple buffers/tabs, jump-to-line, autosave, Ctrl-S save

Contract with buffer.py (Person B):
  - Buffer is UI-agnostic. Drive it via:
      buf.move_cursor(dx, dy, extend_selection=bool)
      buf.insert_char(ch) / insert_newline() / backspace() / delete_char()
      buf.insert_tab() / indent_selection()
      buf.copy() / cut() / paste()
      buf.undo() / buf.redo()
      buf.update_scroll(viewport_height, viewport_width)  # call every frame
  - Read buf.lines, buf.cursor_x/cursor_y, buf.scroll_x/scroll_y to render.
  - buf.modified tells you whether to prompt on quit / show a dirty marker.

This stub just proves the wiring end-to-end (Phase 1 gate: open -> move ->
edit -> save -> exit) without real curses, so `make run` works on day 0.
Replace `run()` with a real curses.wrapper(...) loop.
"""

from __future__ import annotations

import curses
import os
import sys
import threading
import time
from typing import Optional, Tuple

from .buffer import Buffer
from .languages import schema
from .perf import PerfMeter, format_bytes
from .extensions import ExtensionAPI, load_extensions, load_requested_extensions
from .explorer import FileExplorer
from . import filemanager
from . import icons
from . import settings
from . import git
from . import clipboard
from .git_panel import GitPanel, init_panel_colors, draw_git_panel, git_panel_key
from .diff_viewer import DiffViewer, init_diff_colors, draw_diff_overlay, diff_viewer_key
from .git_gutter import GitGutter, get_gutter, init_gutter_colors, draw_gutter_mark, clear_gutter_cache
from .quick_open import QuickOpen
from . import recent
from . import completion
from . import dashboard
from . import themes
from . import imageviewer
from . import pickdir
from . import suggest
from .import codeium
from . import runner
from . import newfile
from . import extview
from .render import safe_render as _safe_render

# Explicit dashboard-owned UI states (UI alignment spec §1).  Each overlay
# lives in exactly one state; none of them instantiate a fake document.
UI_DASHBOARD = "dashboard"
UI_FIND_FILE = "find_file"
UI_RECENT_FILES = "recent_files"
UI_NEW_FILE = "new_file"
UI_EXTENSIONS = "extensions"
UI_RUN_OUTPUT = "run_output"
UI_SETTINGS = "settings"
UI_HELP = "help"

_COLOR_PAIRS = {
    "keyword": 1,
    "string": 2,
    "comment": 3,
    "number": 4,
    "function": 5,
    "type": 6,
    "operator": 7,
    "tag": 8,
    "attribute": 9,
    "property": 10,
}

_PASTE_END = "\x1b[201~"

_AUTO_SAVE_POLL_MS = 250
_AUTO_SAVE_IDLE_DELAY = 5.0
_AUTO_SAVE_PERIODIC_DELAY = 30.0


def _autosave_step(buf, idle_active: bool, periodic_active: bool,
                   last_edit_time: float, last_save_time: float,
                   now: float) -> tuple[bool, str | None]:
    """Perform at most one auto-save according to the active mode.

    Returns ``(saved, error_message)``.  ``error_message`` is set (and
    ``saved`` is False) when the write fails; the caller shows it in the
    status bar instead of letting the exception escape the main loop.
    """
    if not (buf.modified and buf.filename):
        return False, None
    try:
        if idle_active and now - last_edit_time >= _AUTO_SAVE_IDLE_DELAY:
            buf.save()
            return True, None
        if (periodic_active
                and now - last_save_time >= _AUTO_SAVE_PERIODIC_DELAY):
            buf.save()
            return True, None
    except (ValueError, OSError) as exc:
        return False, str(exc)
    return False, None


def _auto_save_on_edit(buf) -> tuple[bool, str | None]:
    """Save immediately for the "on every edit" mode.

    Returns ``(saved, error_message)`` like :func:`_autosave_step`.  The
    caller gates this on the ``auto_save_on_edit`` setting.
    """
    if not buf.filename:
        return False, None
    try:
        buf.save()
        return True, None
    except (ValueError, OSError) as exc:
        return False, str(exc)


def _apply_font_family() -> None:
    """Send OSC 50 escape to switch terminal font to the active font family."""
    font_name = settings.get_active_font_name()
    if not font_name:
        return
    try:
        import sys
        sys.stdout.write(f"\033]50;{font_name}\007")
        sys.stdout.flush()
    except Exception:
        pass


def _apply_active_theme() -> None:
    """Re-apply the active theme to every color pair."""
    themes.apply_theme(settings.get_active_theme_name() or "default")


def _setting_key_group(key: str) -> str | None:
    """Return the radio-group name a setting key belongs to (or None)."""
    groups = settings.RADIO_GROUPS
    for gname, gkeys in groups.items():
        if key in gkeys:
            return gname
    return None


def _settings_sections() -> list[str]:
    """Return the settings section labels in LABELS order."""
    return [label for key, label in settings.LABELS if key is None and label]


def _settings_close_others(expanded: dict[str, bool], keep: str | None) -> None:
    """Collapse every settings section except *keep* (None keeps none).

    Gives the panel single-open (accordion) behavior: opening or moving to
    a section closes any other open section.
    """
    for label in _settings_sections():
        if label != keep:
            expanded[label] = False


def _settings_nav_indices(expanded: dict[str, bool]) -> list[int]:
    """Return LABELS indices of navigable settings rows.

    Section headers are always navigable; a setting row is navigable only
    while its section is expanded.  With every section collapsed this is
    exactly the header rows, which turns the panel into a dropdown list.
    """
    result: list[int] = []
    section: str | None = None
    for i, (key, label) in enumerate(settings.LABELS):
        if key is None:
            if label:
                section = label
                result.append(i)
        elif section is not None and expanded.get(section, False):
            result.append(i)
    return result


def _settings_display_rows(expanded: dict[str, bool]) -> list[tuple]:
    """Build the visible panel rows honoring *expanded* sections.

    Row shapes: ("header", label, lbl_idx), ("separator",),
    ("gap",), ("item", key, label, on, lbl_idx).
    """
    rows: list[tuple] = []
    section: str | None = None
    last_was_item = False
    for lbl_idx, (key, label) in enumerate(settings.LABELS):
        if key is None:
            if label:
                section = label
                rows.append(("header", label, lbl_idx))
                if expanded.get(label, False):
                    rows.append(("separator",))
                last_was_item = False
            else:
                if last_was_item:
                    rows.append(("gap",))
                last_was_item = False
        elif section is not None and expanded.get(section, False):
            rows.append(("item", key, label, settings.get(key), lbl_idx))
            last_was_item = True
        else:
            last_was_item = False
    return rows


def _settings_display_layout(expanded: dict[str, bool], selected_idx: int,
                             draw_height: int) -> tuple[list[tuple], int]:
    """Return (visible rows, scroll start) centered on the selection."""
    rows = _settings_display_rows(expanded)
    sel_pos = 0
    for pos, row in enumerate(rows):
        if row[0] in ("header", "item") and row[-1] == selected_idx:
            sel_pos = pos
            break
    start_idx = max(0, sel_pos - draw_height // 2)
    return rows, start_idx


class EditorContext:
    """Small extension-facing editor context shared with the core TUI."""
    def __init__(self, buf: Buffer, stdscr=None):
        self.buffer = buf
        self.stdscr = stdscr
        self.status = ""
        self.quit_requested = False


def _draw_centered_message(stdscr, line: str, height: int, width: int,
                           y: int = None) -> None:
    if y is None:
        y = max(0, height // 2)
    x = max(0, (width - len(line)) // 2)
    try:
        stdscr.addstr(y, x, _safe_render(line[: width - x]))
    except (curses.error, ValueError, UnicodeEncodeError):
        pass


def _forget_image_pixels(st: dict) -> None:
    """Drop the decoded pixel cache for the image-viewer state dict.

    Zoom/pan are kept so re-entering the viewer preserves the view; the
    pixels are re-decoded on the next entry. Releasing them here is what
    stops a large image from staying resident for the whole session.
    """
    st["pixels"] = None
    st["decoded"] = False
    st["error"] = None


def _image_viewer_frame(stdscr, buf: Buffer, st: dict) -> Optional[str]:
    """Render and drive one frame of the integrated image viewer.

    Returns 'quit', 'exit', or None (keep viewing).
    """
    height, width = stdscr.getmaxyx()
    cell_w = width
    cell_h = max(1, height - 1)
    fmt = buf.image_format or "unknown"
    path = buf.image_path
    st["path"] = path

    if st.get("error") is None and not st.get("decoded"):
        st["decoded"] = True
        try:
            if path and fmt in imageviewer.DECODERS:
                with open(path, "rb") as fh:
                    data = fh.read()
                st["width"], st["height"], st["pixels"] = imageviewer.decode_image(
                    fmt, data)
            elif fmt not in imageviewer.DECODERS:
                st["error"] = (f"{fmt} has no stdlib decoder — "
                               "press v for fullscreen passthrough")
            else:
                st["error"] = "image file could not be read"
        except Exception as exc:  # noqa: BLE001
            st["error"] = f"decode failed: {exc} (v: passthrough)"

    if st.get("pixels") is not None:
        base = imageviewer.fit_scale(st["width"], st["height"], cell_w, cell_h)
        if st.get("fit", True):
            st["zoom"] = 1.0
        scale = base * st.get("zoom", 1.0)
        cells = imageviewer.build_cells(
            st["width"], st["height"], st["pixels"],
            cell_w, cell_h, scale,
            st.get("pan_x", 0), st.get("pan_y", 0),
        )
        imageviewer.draw(stdscr, cells, cell_w, cell_h,
                         imageviewer.make_pairs_state(), 0, 0,
                         background=(8, 10, 14))
        title = imageviewer.image_status_text(
            path, st["width"], st["height"], fmt,
            round(scale * 100), "render")
    else:
        stdscr.erase()
        _draw_centered_message(stdscr, st.get("error", "no image"), height, width)
        title = imageviewer.image_status_text(path, 0, 0, fmt, 0, "viewer")

    hint = imageviewer.viewer_hints(fmt)
    base = imageviewer.fit_scale(st.get("width", 0), st.get("height", 0),
                                 cell_w, cell_h)
    try:
        stdscr.addstr(height - 1, 0, _safe_render(title[: width - 1].ljust(width - 1)),
                      curses.A_REVERSE)
        if base <= 0:
            stdscr.addstr(height - 2, 0, _safe_render(hint[: width - 1]), curses.A_DIM)
    except (curses.error, ValueError, UnicodeEncodeError):
        pass
    stdscr.refresh()

    key = _get_key(stdscr)
    if key in ("q", "\x1b", "\x1c"):  # exit / Esc / Ctrl-\ toggle
        return "exit"
    if key == "\x11":  # Ctrl-Q
        return "quit"
    if key in ("v", "V"):
        imageviewer.stream_fullscreen(stdscr, path, fmt)
        return None
    if st.get("pixels") is None:
        return None

    if key in ("+", "="):
        st["zoom"] = min(64.0, st.get("zoom", 1.0) * 1.25)
        st["fit"] = False
    elif key in ("-", "_"):
        st["zoom"] = max(0.05, st.get("zoom", 1.0) / 1.25)
        st["fit"] = False
    elif key in ("r", "R") or key == curses.KEY_HOME:
        st["zoom"], st["pan_x"], st["pan_y"], st["fit"] = 1.0, 0, 0, True
    elif key == curses.KEY_END:
        if base > 0:
            st["zoom"] = 1.0 / base
            st["fit"] = False
            st["pan_x"], st["pan_y"] = 0, 0
    elif key == curses.KEY_UP:
        st["pan_y"] = max(0, st.get("pan_y", 0) - 6)
    elif key == curses.KEY_DOWN:
        st["pan_y"] = st.get("pan_y", 0) + 6
    elif key == curses.KEY_LEFT:
        st["pan_x"] = max(0, st.get("pan_x", 0) - 6)
    elif key == curses.KEY_RIGHT:
        st["pan_x"] = st.get("pan_x", 0) + 6
    elif key == curses.KEY_PPAGE:
        st["pan_y"] = max(0, st.get("pan_y", 0) - 24)
    elif key == curses.KEY_NPAGE:
        st["pan_y"] = st.get("pan_y", 0) + 24
    return None


def run(buf: Buffer, extension_names=None, extension_files=None, load_all_extensions: bool = False, project_dir=None, tree_on_start: bool = False) -> None:
    """Entry point. Wraps curses so the terminal is restored on crash/exit."""
    curses.wrapper(_curses_main, buf, extension_names or [], extension_files or [], load_all_extensions, project_dir, tree_on_start)


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    active = settings.get_active_theme_name() or "default"
    themes.apply_theme(active)


def _enable_bracketed_paste() -> None:
    """Ask the terminal to wrap pasted text in ESC[200~ ... ESC[201~ markers
    instead of streaming it in as if it were typed. Without this, a paste of
    already-indented multi-line text gets fed through the same path as real
    keystrokes, so every embedded newline triggers auto-indent *on top of*
    the indentation already in the pasted text — indentation doubles every
    line. This is the same mechanism vim/nano/VS Code's terminal use."""
    try:
        sys.stdout.write("\x1b[?2004h")
        sys.stdout.flush()
    except Exception:
        pass


def _disable_bracketed_paste() -> None:
    try:
        sys.stdout.write("\x1b[?2004l")
        sys.stdout.flush()
    except Exception:
        pass


def _read_bracketed_paste(stdscr) -> str:
    """Read a terminal bracketed-paste payload.

    The main loop has already consumed ESC and the following ``[`` before
    calling this function, so only ``200~`` remains in the start marker.
    Previously this function tried to consume ``[200~`` again. That consumed
    the first character (``2``) while expecting ``[`` and returned early,
    leaving ``00~`` in curses' input queue. The remaining pasted newlines were
    then treated as real Enter keypresses, so auto-indent ran on every pasted
    line and indentation grew recursively.
    """
    for expected in "200~":
        ch = stdscr.getch()
        if ch == -1 or chr(ch) != expected:
            return ""  # malformed sequence; bail out safely

    content = []
    end_marker = _PASTE_END
    tail = []
    while True:
        ch = stdscr.getch()
        if ch == -1:
            continue
        tail.append(chr(ch))
        if len(tail) > len(end_marker):
            content.append(tail.pop(0))
        if "".join(tail) == end_marker:
            return "".join(content)
        if len(content) + len(tail) > 2_000_000:  # sanity cap
            content.extend(tail)
            return "".join(content)


def _is_ctrl_enter_csi(stdscr) -> bool:
    """Return True if the current input is Ctrl+Enter and consume it.

    Some terminals send Ctrl+Enter as its own CSI sequence rather than a
    bare ``\\r`` (which is indistinguishable from Enter).  Recognized forms:
      ``ESC [ 1 3 ; 5 u``   (modified-key / CSI-u protocol, e.g. kitty)
      ``ESC [ 2 7 ; 5 1 3 ~`` (classic xterm encoding)
    The main loop has already consumed ``ESC`` but not the ``[``.

    When the sequence does not match, every character read here is pushed
    back with ``ungetch`` so the bracketed-paste parser below sees the
    untouched stream (a plain ``ESC [`` prefix is shared by both).
    """
    stdscr.nodelay(True)
    try:
        consumed = []
        for _ in range(16):
            ch = stdscr.getch()
            if ch == -1:
                break
            consumed.append(chr(ch))
            # End of a CSI code is a single byte in @-~; the leading '[' is
            # part of the sequence, not its terminator.
            if 0x40 <= ch <= 0x7E and ch != ord("["):
                break
        seq = "".join(consumed)
        if seq in ("[13;5u", "[27;5;13~"):
            return True
        for c in reversed(consumed):
            curses.ungetch(ord(c))
        return False
    finally:
        stdscr.nodelay(False)


def _is_ctrl_1(stdscr) -> bool:
    """Return True when the input stream is a CSI-u Ctrl+1 sequence.

    Terminals that implement the CSI-u protocol encode Ctrl+1 distinctly
    from ESC: ``ESC [ 4 9 ; 5 u`` (xterm style) or ``ESC [ 4 9 : 5 u``
    (kitty).  The main loop has already consumed ``ESC``; a following ``[``
    is expected.  Terminals without CSI-u cannot disambiguate Ctrl+1 from a
    plain ``1`` and simply report ``1`` — that is beyond the app's control.

    When the sequence does not match, every character read here is pushed
    back so the caller still sees the untouched stream.
    """
    stdscr.nodelay(True)
    try:
        consumed = []
        for _ in range(16):
            ch = stdscr.getch()
            if ch == -1:
                break
            consumed.append(chr(ch))
            # End of a CSI code is a single byte in @-~; the leading '[' is
            # part of the sequence, not its terminator.
            if 0x40 <= ch <= 0x7E and ch != ord("["):
                break
        seq = "".join(consumed)
        if seq in ("[49;5u", "[49:5u", "[1;5u"):
            return True
        for c in reversed(consumed):
            curses.ungetch(ord(c))
        return False
    finally:
        stdscr.nodelay(False)
# ---------------------------------------------------------------------- #
_search: dict = {
    "query": "",
    "replace": "",
    "matches": [],
    "idx": 0,
    "anchor": None,
    "mode": "find",
    "replacements": [],
}

_mouse_dragging: bool = False
_last_click_time: float = 0.0
_click_count: int = 0
_CLICK_THRESHOLD: float = 0.4


def _overlay_signature(qo, recent_picker, show_settings, settings_idx,
                       expanded_sections, show_help, help_scroll,
                       help_total, height, width) -> tuple:
    """Fingerprint the visible state of every editor-path overlay.

    The main loop repaints an overlay only when this signature changes
    (dirty-frame skip): once the content settles — typing stopped, results
    loaded, selection idle — the signature is stable and the TUI performs
    zero draw calls per poll.  That is what removes the 50 ms full-screen
    shutter while the user is typing and the per-keystroke repaint churn.
    """
    parts = [height, width]
    parts.append(1 if qo.visible else 0)
    if qo.visible:
        parts += [qo.query, qo.selected_idx, len(qo.results),
                  qo.loading, qo.scoring, qo.scan_error, qo.capped]
    parts.append(1 if recent_picker.active else 0)
    if recent_picker.active:
        parts += [recent_picker.selected, tuple(recent_picker.entries)]
    parts.append(1 if show_settings else 0)
    if show_settings:
        values = tuple(sorted(
            (k, settings.get(k)) for k, _ in settings.LABELS if k))
        parts += [settings_idx, tuple(sorted(expanded_sections.items())),
                  values]
    parts.append(1 if show_help else 0)
    if show_help:
        parts += [help_scroll, help_total, height]
    return tuple(parts)


def _curses_main(stdscr, buf: Buffer, extension_names=None, extension_files=None, load_all_extensions: bool = False, project_dir=None, tree_on_start: bool = False) -> None:
    """
    TEMPORARY minimal UI — just enough to test buffer.py interactively.
    Person A will replace this with the real thing (line numbers, status
    bar, word-wrap, tabs, etc. per the plan). Keymap here is intentionally
    small: arrows, typing, backspace/delete, ctrl-s save, ctrl-z/y undo/redo,
    ctrl-q quit.
    """
    # Raw mode is required for reliable editor control keys (Ctrl-Q, Ctrl-S,
    # Ctrl-Z, etc.). In normal cbreak mode the terminal driver may consume
    # flow-control keys such as Ctrl-S/Ctrl-Q before curses receives them.
    # curses.wrapper() still restores the terminal state on exit.
    curses.raw()
    curses.noecho()
    curses.curs_set(1)
    stdscr.keypad(True)
    _init_colors()
    init_panel_colors()
    init_diff_colors()
    init_gutter_colors()
    _apply_font_family()
    _enable_bracketed_paste()
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    curses.mouseinterval(0)
    icons_on = icons.enabled_from_env()
    dashboard.init_colors()

    language = schema.detect_language(buf.filename or "")
    buf.configure_for_language(language)
    selecting = False
    meter = PerfMeter(interval=0.5)
    editor = EditorContext(buf, stdscr)
    explorer = FileExplorer(".")
    root_dir = resolve_tree_root(buf.filename, project_dir)
    git_panel = GitPanel(root_dir if root_dir != "." else os.path.dirname(os.path.abspath(buf.filename)) if buf.filename else ".")
    diff_viewer = DiffViewer()
    if root_dir != ".":
        explorer.set_root(root_dir)
    if buf.filename and os.path.isfile(buf.filename):
        explorer.current_path = os.path.abspath(buf.filename)
    extensions = ExtensionAPI(editor)
    if load_all_extensions:
        loaded, extension_errors = load_extensions(extensions)
    elif extension_names or extension_files:
        loaded, extension_errors = load_requested_extensions(extensions, extension_names or [], extension_files or [])
    else:
        loaded, extension_errors = [], []
    extensions.startup()

    try:
        status = f"Loaded extensions: {', '.join(loaded)}" if loaded else ""
        if extension_errors:
            status = (status + "  " if status else "") + f"{len(extension_errors)} extension error(s)"
        hint = "File tree active — Enter opens file/folder, Esc to focus editor, Ctrl-H help"
        status = (status + "   " if status else "") + hint
        if buf.image_format is not None and buf.filename:
            # Image passed on the command line: open it in the default
            # browser the same way in-editor opens do.
            opened, _ = runner.open_in_browser(buf.filename)
            note = (f"Opened {buf.filename} in the default browser"
                    if opened else "Could not open image in browser")
            status = (status + "   " if status else "") + note
        _main_loop(stdscr, buf, language, status, selecting, meter, extensions, editor, explorer, icons_on, root_dir, git_panel, diff_viewer, project_dir, tree_on_start)
    finally:
        extensions.shutdown()
        _disable_bracketed_paste()


def _main_loop(stdscr, buf: Buffer, language: str, status: str, selecting: bool, meter: PerfMeter, extensions: ExtensionAPI, editor: EditorContext, explorer: FileExplorer, icons_on: bool = False, root_dir: str = ".", git_panel: GitPanel | None = None, diff_viewer: DiffViewer | None = None, project_dir: str | None = None, tree_on_start: bool = False) -> None:
    show_help = False
    show_settings = False
    settings_idx = 0
    help_scroll = 0
    expanded_sections: dict[str, bool] = {}
    _last_edit_time = time.time()
    _last_save_time = time.time()
    if tree_on_start:
        explorer.visible = True
        explorer.active = True
        _startup_tree(explorer, buf.filename)
    _git_branch = None
    _git_counts: dict[str, int] = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0}
    _git_refresh_time = 0.0
    _git_refresh_interval = 2.0  # seconds between git status refreshes
    dashboard_active = (buf.filename is None and project_dir is None)
    image_view_active = False
    image_state = {
        "pixels": None, "width": 0, "height": 0,
        "error": None, "decoded": False,
        "zoom": 1.0, "pan_x": 0, "pan_y": 0,
        "path": buf.image_path,
    }
    search_root = os.path.expanduser("~") if dashboard_active else root_dir
    package_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    excluded_search_roots = [package_root] if dashboard_active else []
    quick_open = QuickOpen(search_root, exclude_roots=excluded_search_roots, show_recent_on_empty=False)
    recent_picker = RecentPicker()
    dashboard_selected = 0
    dashboard_started = time.perf_counter()
    dashboard_message = ""
    # Explicit dashboard-overlay state: None means the base YUKI screen.
    # Overlays are composed over the dashboard and never instantiate a
    # fake/blank document buffer (UI alignment spec §1, §3).
    dashboard_overlay: str | None = None
    new_file_picker = newfile.NewFilePicker()
    ext_view = extview.ExtensionsView()
    # Dirty-frame skip: the last overlay signature that was actually painted.
    # Equal signature on the next poll => skip erase/base/overlay/refresh.
    overlay_last_sig: tuple | None = None
    _help_sig_width = -1
    _help_sig_total = 0
    sug = suggest.Suggestor()
    sug_words: "object" = {}
    sug_fp = None
    ghost = None
    ghost_anchor = (-1, -1)
    ghost_busy = False
    last_buffer_change_at = time.monotonic()

    # Git gutter for inline diff markers
    gutter: GitGutter | None = None
    if buf.filename and git.is_git_repo(root_dir):
        gutter = get_gutter(root_dir, buf.filename)
        gutter.maybe_refresh(buf.get_text())

    def _ghost_run() -> None:
        nonlocal ghost, ghost_anchor, ghost_busy
        try:
            result = _fetch_ghost_text(editor.buffer)
        except Exception:
            result = None
        if result is not None:
            if (result.range_start_y, result.range_start_x) == (
                editor.buffer.cursor_y, editor.buffer.cursor_x):
                ghost = result
                ghost_anchor = (result.range_start_y, result.range_start_x)
            else:
                ghost = None
                ghost_anchor = (-1, -1)
        ghost_busy = False
    while True:
        frame_started = meter.frame_start()
        if dashboard_active:
            if dashboard_overlay in (UI_NEW_FILE, UI_EXTENSIONS):
                # One composed frame, single refresh: the dashboard is drawn
                # without refreshing, the overlay is painted on top, then the
                # terminal is refreshed exactly once (no camera-shutter
                # flicker).
                meter.frame_end(frame_started)
                dashboard.draw(
                    stdscr,
                    dashboard_selected,
                    time.perf_counter() - dashboard_started,
                    format_bytes(meter.rss),
                    message=dashboard_message,
                    refresh=False,
                )
                _ov_h, _ov_w = stdscr.getmaxyx()
                if dashboard_overlay == UI_NEW_FILE:
                    newfile.draw(stdscr, new_file_picker, _ov_h, _ov_w)
                else:
                    extview.draw(stdscr, ext_view, _ov_h, _ov_w)
                stdscr.refresh()
                key = _get_key(stdscr)
                if key == "\x1b" and _is_ctrl_1(stdscr):
                    key = newfile.CTRL_1
                if dashboard_overlay == UI_NEW_FILE:
                    action = new_file_picker.handle_key(key)
                    if action == "created":
                        path = os.path.join(new_file_picker.cwd,
                                            new_file_picker.filename)
                        dashboard_overlay = None
                        dashboard_message = ""
                        language, status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                        )
                        if status.startswith("Opened"):
                            buf.configure_for_language(language)
                            explorer.active = False
                        else:
                            # Creation succeeded, opening failed: revert to
                            # the base dashboard instead of dying.
                            dashboard_active = True
                            dashboard_message = status
                            continue
                        dashboard_active = False
                        continue
                    if action == "dashboard":
                        dashboard_overlay = None
                        dashboard_message = ""
                    continue
                # Extensions overlay keys.
                if key in (newfile.CTRL_1, "\x1b"):
                    ext_view.close()
                    dashboard_overlay = None
                    dashboard_message = ""
                    continue
                if key == curses.KEY_UP:
                    ext_view.move(-1)
                    continue
                if key == curses.KEY_DOWN:
                    ext_view.move(1)
                    continue
                continue
            overlay_open = (quick_open.visible or recent_picker.active
                            or show_settings or show_help)
            if not overlay_open:
                meter.frame_end(frame_started)
                dashboard.draw(
                    stdscr,
                    dashboard_selected,
                    time.perf_counter() - dashboard_started,
                    format_bytes(meter.rss),
                    message=dashboard_message,
                )
                key = _get_key(stdscr)
                dashboard_message = ""
                if key in ("q", "Q", "\x11"):
                    return
                if key in (curses.KEY_UP,):
                    dashboard_selected = (dashboard_selected - 1) % dashboard.action_count()
                    continue
                if key in (curses.KEY_DOWN, "\t"):
                    dashboard_selected = (dashboard_selected + 1) % dashboard.action_count()
                    continue
                if key in ("\n", "\r", " "):
                    key = dashboard.action_key(dashboard_selected)
                if key in ("f", "F"):
                    # Search overlay is composed over the live dashboard; the
                    # dashboard remains the base frame (no blank editor behind
                    # the box), so dashboard_active stays True.
                    explorer.set_root(os.path.expanduser("~"))
                    explorer.active = False
                    explorer.visible = False
                    quick_open.mode = "files"
                    quick_open.open()
                    stdscr.timeout(50)
                    continue
                if key in ("d", "D"):
                    explorer.set_root(os.path.expanduser("~"))
                    explorer.active = False
                    explorer.visible = False
                    quick_open.mode = "folders"
                    quick_open.open()
                    stdscr.timeout(50)
                    continue
                if key in ("r", "R"):
                    recent_picker.open()
                    stdscr.timeout(50)
                    continue
                if key in ("e", "E"):
                    ext_view.open()
                    dashboard_overlay = UI_EXTENSIONS
                    continue
                if key in ("o", "O"):
                    result = pickdir.choose_directory()
                    if result[0] == "ok":
                        dashboard_active = False
                        explorer.set_root(result[1])
                        explorer.visible = True
                        explorer.active = True
                        root_dir = result[1]
                        quick_open = QuickOpen(root_dir, show_recent_on_empty=False)
                        status = f"Folder browser: {result[1]} — Enter opens files/folders, Esc to focus the editor"
                    elif result[0] == "cancelled":
                        dashboard_message = "Folder dialog cancelled"
                    else:
                        dashboard_active = False
                        explorer.set_root(os.path.expanduser("~"))
                        explorer.visible = True
                        explorer.active = True
                        root_dir = os.path.expanduser("~")
                        quick_open = QuickOpen(root_dir, show_recent_on_empty=False)
                        status = "System folder dialog unavailable — browsing home"
                    continue
                if key in ("n", "N"):
                    # Folder-first New File workflow: pick a directory, type a
                    # name, Enter creates it and opens the real file (spec §2).
                    new_file_picker.open()
                    dashboard_overlay = UI_NEW_FILE
                    continue
                if key in ("c", "C"):
                    show_settings = True
                    explorer.visible = False
                    continue
                if key in ("s", "S"):
                    items = recent.get_recent()
                    path = next((p for p in items if os.path.isfile(p)), None)
                    if path:
                        language, status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                        )
                        if status.startswith("Opened"):
                            buf.configure_for_language(language)
                            explorer.active = False
                            dashboard_active = False
                    else:
                        status = "No recent file to restore"
                    continue
                if key in ("h", "H") or key == curses.KEY_F1:
                    show_help = True
                    help_scroll = 0
                    continue
                continue
            # A Quick Open / Recent / Settings / Help overlay is open over the
            # dashboard: fall through to the shared frame + key path below so
            # the overlay handlers receive the keys while the dashboard stays
            # as the base frame behind the box.
        if buf.image_format is not None and image_view_active:
            meter.frame_end(frame_started)
            action = _image_viewer_frame(stdscr, buf, image_state)
            if action == "quit":
                return
            if action == "exit":
                image_view_active = False
                _forget_image_pixels(image_state)
                status = "Raw binary view — Ctrl-\\ re-opens the image viewer"
            continue
        if (buf.image_format is not None
                and image_state.get("path") != buf.image_path):
            _forget_image_pixels(image_state)
            image_state["path"] = buf.image_path
        height, width = stdscr.getmaxyx()
        text_height = height - 1  # reserve last row for status line

        # Calculate explorer width — proportional to terminal width
        # Settings panel replaces explorer when open (same slot, same style).
        if show_settings:
            explorer_width = 0
            settings_panel_width = min(35, max(22, width // 3))
        else:
            explorer_width = (min(25, max(18, width // 4))
                              if explorer.visible else 0)
            settings_panel_width = 0

        # Calculate git panel width — proportional to terminal width
        git_panel_width = (min(30, max(20, width // 5))
                           if git_panel and git_panel.visible else 0)

        # Combined left offset: explorer + settings panel
        left_offset = explorer_width + settings_panel_width

        # Dirty-frame skip: while a Quick Open / Recent / Settings / Help
        # overlay is open, repaint the whole frame only when its visible
        # state changed.  Once the content settles the TUI does zero draw
        # calls per poll, which removes the screen shutter while typing and
        # stops the per-keystroke repaint churn.
        ignore = False
        overlay_open = (quick_open.visible or recent_picker.active
                        or show_settings or show_help)
        if not overlay_open:
            overlay_last_sig = None
        else:
            if show_help and _help_sig_width != width:
                _help_sig_width = width
                _help_sig_total = len(build_help_lines(width))
            sig = _overlay_signature(
                quick_open, recent_picker, show_settings, settings_idx,
                expanded_sections, show_help, help_scroll, _help_sig_total,
                height, width)
            ignore = sig == overlay_last_sig
            if not ignore:
                overlay_last_sig = sig

        # Draw file explorer if visible (not when settings panel is open)
        if not ignore:
            if dashboard_active:
                # The intact YUKI screen is the base under every overlay: the
                # box is painted on top of the real dashboard and the terminal
                # is refreshed exactly once (no blank editor page, no shutter).
                dashboard.draw(
                    stdscr,
                    dashboard_selected,
                    time.perf_counter() - dashboard_started,
                    format_bytes(meter.rss),
                    message=dashboard_message,
                    refresh=False,
                )
                if show_settings:
                    _draw_settings_overlay(stdscr, settings_idx,
                                           settings_panel_width,
                                           expanded_sections)
            else:
                stdscr.erase()
                if explorer.visible and not show_settings:
                    _draw_explorer(stdscr, explorer, text_height,
                                   explorer_width, icons_on)

                # Draw settings panel (replaces explorer as left sidebar)
                if show_settings:
                    _draw_settings_overlay(stdscr, settings_idx,
                                           settings_panel_width,
                                           expanded_sections)

                # Handle diff overlay early (covers full screen)
                if git_panel and git_panel.visible and git_panel.mode == "diff":
                    if diff_viewer and not diff_viewer.diff_text:
                        diff_text = git_panel.get_selected_diff()
                        f = git_panel.selected_file()
                        title = f.path if f else "diff"
                        diff_viewer.load(diff_text, title=title)
                    if diff_viewer:
                        draw_diff_overlay(stdscr, diff_viewer, height, width)
                        stdscr.move(height - 1, 0)
                        status_line = format_status_bar(
                            filename=buf.filename, modified=buf.modified,
                            label=schema.language_label(language),
                            cursor_y=buf.cursor_y, cursor_x=buf.cursor_x,
                            line_count=len(buf.lines),
                            width=width,
                            git_branch=_git_branch, git_counts=_git_counts,
                        )
                        try:
                            stdscr.addstr(height - 1, 0, _safe_render(status_line[:width - 1]),
                                          curses.A_REVERSE | curses.A_BOLD)
                        except (curses.error, ValueError, UnicodeEncodeError):
                            pass
                        try:
                            stdscr.move(buf.cursor_y - buf.scroll_y, 0)
                        except curses.error:
                            pass
                        if frame_started:
                            meter.frame_end(frame_started)
                        continue

                gutter_width = line_number_width(len(buf.lines)) + 3  # +1 for git gutter marker
                text_width = max(1, width - left_offset - gutter_width - git_panel_width)

                buf.update_scroll(text_height, text_width)

                # Refresh gutter if buffer changed
                if gutter and buf.filename:
                    gutter.maybe_refresh(buf.get_text())

                for row in range(text_height):
                    line_idx = buf.scroll_y + row
                    _draw_gutter(stdscr, row, line_idx, len(buf.lines), gutter_width, x_offset=left_offset)
                    # Draw git gutter marker after line number
                    if gutter and line_idx < len(buf.lines):
                        mark = gutter.get_mark(line_idx + 1)  # 1-indexed
                        if mark:
                            draw_gutter_mark(stdscr, row, left_offset + line_number_width(len(buf.lines)) + 1, mark)
                    if line_idx >= len(buf.lines):
                        continue
                    line = buf.lines[line_idx]
                    _draw_line(
                        stdscr, row, line, buf.scroll_x, text_width, language,
                        x_offset=gutter_width + left_offset,
                    )
                    _highlight_selection(
                        stdscr, row, line_idx, line, buf,
                        scroll_x=buf.scroll_x, width=text_width, x_offset=gutter_width + left_offset,
                    )
                    _highlight_find_match(
                        stdscr, row, line_idx, text_width, buf.scroll_x,
                        gutter_width + left_offset,
                    )

                # Draw git panel on the RIGHT side (after editor content)
                if git_panel and git_panel.visible:
                    git_panel_x = left_offset + gutter_width + text_width
                    draw_git_panel(stdscr, git_panel, text_height, git_panel_width,
                                   x_offset=git_panel_x)

                match = buf.matching_bracket()

                # Refresh git info periodically (not every frame)
                now_frame = time.time()
                if now_frame - _git_refresh_time >= _git_refresh_interval:
                    _git_refresh_time = now_frame
                    project = root_dir if root_dir != "." else (os.path.dirname(buf.filename) if buf.filename else ".")
                    if git.is_git_repo(project):
                        _git_branch = git.get_branch(project)
                        _git_counts = git.get_status_counts(project)
                        # Also refresh git panel if visible
                        if git_panel and git_panel.visible:
                            git_panel.refresh()
                    else:
                        _git_branch = None
                        _git_counts = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0}

                status_line = format_status_bar(
                    filename=buf.filename,
                    modified=buf.modified,
                    label=schema.language_label(language),
                    cursor_y=buf.cursor_y,
                    cursor_x=buf.cursor_x,
                    line_count=len(buf.lines),
                    selecting=selecting,
                    large_file_mode=buf.large_file_mode,
                    match_pos=match,
                    meter_label=meter.label(),
                    extension_status=extensions.status(),
                    transient_status=status,
                    icon=icons.icon_for_language(schema.language_label(language), icons_on),
                    width=width,
                    git_branch=_git_branch,
                    git_counts=_git_counts,
                )
                try:
                    stdscr.addstr(height - 1, 0, _safe_render(status_line), curses.A_REVERSE)
                except (curses.error, ValueError, UnicodeEncodeError):
                    pass

            if show_help:
                _draw_help_overlay(stdscr, build_help_lines(width),
                                   help_scroll)
            if quick_open.visible:
                _draw_quick_open_overlay(stdscr, quick_open)
            else:
                _qo_last_rect = None
            if recent_picker.active:
                _draw_recent_overlay(stdscr, recent_picker, height, width)

            if (sug.visible and not (show_settings or show_help
                                     or explorer.active or image_view_active)
                    and not dashboard_active):
                _draw_suggest_overlay(stdscr, sug, buf, left_offset, gutter_width,
                                      text_width, height, width)
            if (ghost is not None
                    and (buf.cursor_y, buf.cursor_x) == ghost_anchor
                    and not dashboard_active):
                _draw_ghost(stdscr, buf, ghost, left_offset, gutter_width,
                            text_width)

            if quick_open.visible:
                # Terminal caret goes inside the box, right after the typed
                # text (never a hidden cursor behind the overlay).
                _cr, _cc = _quick_open_cursor_col(quick_open, height, width)
                try:
                    stdscr.move(_cr, _cc)
                except curses.error:
                    pass
            elif not dashboard_active:
                stdscr.move(
                    buf.cursor_y - buf.scroll_y,
                    left_offset + gutter_width + min(buf.cursor_x - buf.scroll_x, max(text_width - 1, 0)),
                )
            stdscr.refresh()
        meter.frame_end(frame_started)
        status = ""

        # Check auto-save timers every frame (including idle polls), so the
        # idle/periodic modes fire even when the user isn't typing. Must run
        # before `_prev_modified` is captured so the next edit correctly
        # restarts the idle clock after a save.
        now = time.time()
        saved, save_error = _autosave_step(
            buf, settings.get("auto_save_idle"), settings.get("auto_save_periodic"),
            _last_edit_time, _last_save_time, now)
        if saved:
            _last_save_time = now
            status = "Auto-saved"
        elif save_error is not None:
            status = f"Auto-save failed: {save_error}"

        _prev_modified = buf.modified
        _editor_idle = not (explorer.active or show_settings or show_help
                            or quick_open.visible or recent_picker.active
                            or image_view_active)
        if settings.get("codeium_on"):
            stdscr.timeout(350 if _editor_idle else 50)
        elif settings.get("auto_save_idle") or settings.get("auto_save_periodic"):
            # Wake up regularly so the idle/periodic timers above get a
            # chance to fire while the user is idle.
            stdscr.timeout(_AUTO_SAVE_POLL_MS)
        key = _get_key(stdscr)
        if key is None:
            # Inline-suggestion debounce: fetch when idle for >= 0.35s.
            if (_editor_idle and not ghost_busy
                    and time.monotonic() - last_buffer_change_at >= 0.35
                    and _ghost_wanted(buf)):
                ghost_busy = True
                threading.Thread(
                    target=_ghost_run, args=(), daemon=True).start()
            continue

        # --- Mouse events (before all other key handling) ---
        if isinstance(key, tuple) and key[0] == "__mouse__":
            if dashboard_active:
                # The dashboard and its overlays don't use the mouse
                # (buffer/gutter geometry isn't even defined on that base).
                continue
            global _mouse_dragging, _last_click_time, _click_count
            _, mx, my, bstate = key
            # Convert screen coords → buffer coords.
            buf_y = buf.scroll_y + my
            buf_x = buf.scroll_x + (mx - gutter_width - left_offset)
            buf_y = max(0, min(buf_y, len(buf.lines) - 1))
            buf_x = max(0, min(buf_x, len(buf.lines[buf_y])))

            # --- Scroll wheel ---
            if bstate & curses.BUTTON4_PRESSED:
                buf.move_cursor(dy=-3)
                buf.update_scroll(text_height, text_width)
                continue
            if bstate & curses.BUTTON5_PRESSED:
                buf.move_cursor(dy=3)
                buf.update_scroll(text_height, text_width)
                continue

            if bstate & curses.BUTTON1_PRESSED:
                # Click on the settings panel → dropdown interaction.
                if show_settings and mx < settings_panel_width and my < text_height:
                    now = time.monotonic()
                    multi = now - _last_click_time < _CLICK_THRESHOLD
                    _last_click_time = now
                    rows, start_idx = _settings_display_layout(
                        expanded_sections, settings_idx, text_height)
                    row_pos = start_idx + my
                    if 0 <= row_pos < len(rows):
                        row = rows[row_pos]
                        if row[0] == "header":
                            if not multi:
                                if expanded_sections.get(row[1], False):
                                    expanded_sections[row[1]] = False
                                else:
                                    _settings_close_others(expanded_sections, row[1])
                                    expanded_sections[row[1]] = True
                            settings_idx = row[2]
                        elif row[0] == "item":
                            settings_idx = row[4]
                    continue
                # Click in text area only.
                if (my < text_height
                        and gutter_width + left_offset <= mx < gutter_width + left_offset + text_width):
                    now = time.monotonic()
                    # Detect multi-click (double / triple).
                    if now - _last_click_time < _CLICK_THRESHOLD and _click_count >= 1:
                        _click_count += 1
                    else:
                        _click_count = 1
                    _last_click_time = now

                    if _click_count >= 3:
                        # Triple-click: select entire line.
                        buf.select_line_at(buf_y)
                        selecting = False
                    elif _click_count == 2:
                        # Double-click: select word.
                        buf.select_word_at(buf_y, buf_x)
                        selecting = False
                    elif bstate & curses.BUTTON_SHIFT:
                        # Shift+click: extend selection to click position.
                        if buf.selection_anchor is None:
                            buf.selection_anchor = (buf_y, buf_x)
                        buf.move_to(buf_x, buf_y, extend_selection=True)
                    else:
                        # Normal click: position cursor, start anchor.
                        buf.move_to(buf_x, buf_y)
                        buf.selection_anchor = (buf_y, buf_x)
                        selecting = False
                    _mouse_dragging = True
                elif my >= text_height:
                    # Click on status bar — ignore.
                    pass
                else:
                    # Click in gutter/explorer — ignore.
                    pass
                continue
            if bstate & curses.BUTTON1_RELEASED:
                _mouse_dragging = False
                continue
            # Motion while dragging (REPORT_MOUSE_POSITION events).
            if _mouse_dragging:
                if (0 <= my < text_height
                        and gutter_width + left_offset <= mx < gutter_width + left_offset + text_width):
                    buf.move_to(buf_x, buf_y, extend_selection=True)
            continue

        # The help guide outranks every other binding (Ctrl-H / F1).
        if is_help_toggle(key, explorer.visible and explorer.active) and not explorer.searching:
            show_help = not show_help
            if show_help:
                help_scroll = 0  # always open at the top
            continue
        if show_help:
            # Scroll, deliberate dismissal; other keys are swallowed.
            total = len(build_help_lines(width))
            view_h = max(1, height - 2)
            if key == "\x1b" and _is_ctrl_1(stdscr):
                ok, msg = _leave_to_dashboard(
                    stdscr, buf,
                    render_unsaved=lambda t: _draw_status_prompt(stdscr, t))
                if ok:
                    show_help = False
                    dashboard_active = True
                else:
                    status = msg
                continue
            if key == curses.KEY_UP:
                help_scroll = clamp_scroll(help_scroll, -1, total, view_h)
            elif key == curses.KEY_DOWN:
                help_scroll = clamp_scroll(help_scroll, 1, total, view_h)
            elif key == curses.KEY_PPAGE:
                help_scroll = clamp_scroll(help_scroll, -view_h, total,
                                           view_h)
            elif key == curses.KEY_NPAGE:
                help_scroll = clamp_scroll(help_scroll, view_h, total,
                                           view_h)
            elif key in ("q", "\x1b", "\n", "\r"):
                show_help = False
            continue

        # Run the current file in an external terminal (F5 / Ctrl+Enter).
        # Handled here, before the ESC dispatch, because Ctrl+Enter arrives
        # as an ESC-prefixed CSI sequence that tree/popup handling would
        # otherwise misread.
        if key == curses.KEY_F5 or (key == "\x1b" and _is_ctrl_enter_csi(stdscr)):
            status = _run_current_file(buf)
            continue

        # Image viewer toggle: current file is an image (Ctrl-\)
        if key in ("\x1c",) and buf.image_path is not None:
            image_view_active = not image_view_active
            status = ("Image viewer on" if image_view_active
                      else "Raw binary view")
            continue

        # Settings overlay (Ctrl-P).
        if key == "\x10" and not explorer.searching:
            show_settings = not show_settings
            nav = _settings_nav_indices(expanded_sections)
            settings_idx = nav[0] if nav else next(
                i for i, (k, _) in enumerate(settings.LABELS) if k is not None)
            continue
        if show_settings:
            nav = _settings_nav_indices(expanded_sections)
            n_items = len(nav)
            if key == curses.KEY_UP:
                cur = nav.index(settings_idx) if settings_idx in nav else 0
                settings_idx = nav[(cur - 1) % n_items]
                if settings.LABELS[settings_idx][0] is None:
                    _settings_close_others(
                        expanded_sections, settings.LABELS[settings_idx][1])
            elif key == curses.KEY_DOWN:
                cur = nav.index(settings_idx) if settings_idx in nav else 0
                settings_idx = nav[(cur + 1) % n_items]
                if settings.LABELS[settings_idx][0] is None:
                    _settings_close_others(
                        expanded_sections, settings.LABELS[settings_idx][1])
            elif key in (" ", "\n", "\r"):
                k, label = settings.LABELS[settings_idx]
                if k is None:
                    if expanded_sections.get(label, False):
                        expanded_sections[label] = False
                    else:
                        _settings_close_others(expanded_sections, label)
                        expanded_sections[label] = True
                else:
                    settings.toggle_radio(k)
                    if _setting_key_group(k) == "theme":
                        _apply_active_theme()
                    _apply_font_family()
            elif key == "\x1b" and _is_ctrl_1(stdscr):
                ok, msg = _leave_to_dashboard(
                    stdscr, buf,
                    render_unsaved=lambda t: _draw_status_prompt(stdscr, t))
                if ok:
                    show_settings = False
                    dashboard_active = True
                else:
                    status = msg
            elif key in ("\x1b", "\x10", "q"):
                show_settings = False
            continue

        # Recent Files picker overlay (from the dashboard).
        if recent_picker.active:
            if key is None:
                continue
            if key == "\x1b" and _is_ctrl_1(stdscr):
                ok, msg = _leave_to_dashboard(
                    stdscr, buf,
                    render_unsaved=lambda t: _draw_status_prompt(stdscr, t))
                if ok:
                    recent_picker.close()
                    stdscr.timeout(-1)
                    dashboard_active = True
                else:
                    status = msg
                continue
            if key in ("\x1b", "q"):
                recent_picker.close()
                stdscr.timeout(-1)
                dashboard_active = True
                continue
            if key in ("\n", "\r"):
                path = recent_picker.selected_path()
                if path:
                    recent_picker.close()
                    stdscr.timeout(-1)
                    language, status = open_file_path(
                        stdscr, buf, explorer, path,
                        render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                    )
                    if status.startswith("Opened"):
                        buf.configure_for_language(language)
                        explorer.active = False
                    dashboard_active = False
                else:
                    recent_picker.close()
                    stdscr.timeout(-1)
                    dashboard_active = True
                    status = "No recent files"
                continue
            if key == curses.KEY_UP:
                recent_picker.move_selection(-1)
                continue
            if key == curses.KEY_DOWN:
                recent_picker.move_selection(1)
                continue
            continue

        # Quick Open overlay (Ctrl-O).
        if quick_open.visible:
            if key is None:
                continue
            if key == "\x1b" and _is_ctrl_1(stdscr):
                ok, msg = _leave_to_dashboard(
                    stdscr, buf,
                    render_unsaved=lambda t: _draw_status_prompt(stdscr, t))
                if ok:
                    quick_open.close()
                    stdscr.timeout(-1)
                    status = ""
                    dashboard_active = True
                else:
                    status = msg
                continue
            if key in ("\x1b", "\x0f"):
                quick_open.close()
                stdscr.timeout(-1)
                status = ""
                dashboard_active = True  # already true from the dashboard
            elif key == "\n" or key == "\r":
                empty_query = not quick_open.query.strip()
                path = quick_open.selected_location()
                if path:
                    quick_open.close()
                    stdscr.timeout(-1)
                    if os.path.isdir(path):
                        explorer.set_root(path)
                        explorer.visible = True
                        explorer.active = True
                        root_dir = path
                        quick_open = QuickOpen(root_dir, show_recent_on_empty=False)
                        status = f"Project root: {path}"
                        dashboard_active = False
                    else:
                        language, status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                        )
                        if status.startswith("Opened"):
                            buf.configure_for_language(language)
                            explorer.active = False
                            recent.add_recent(path)
                            dashboard_active = False
                        else:
                            dashboard_active = True
                else:
                    quick_open.close()
                    stdscr.timeout(-1)
                    if dashboard_active and empty_query:
                        # Empty query + Enter on the dashboard overlay
                        # returns to YUKI.
                        status = ""
                    else:
                        status = ("No folder selected" if quick_open.mode == "folders"
                                  else "No file selected")
            elif key == curses.KEY_UP:
                quick_open.move_selection(-1)
            elif key == curses.KEY_DOWN:
                quick_open.move_selection(1)
            elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                quick_open.update_query(quick_open.query[:-1])
            elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                quick_open.update_query(quick_open.query + key)
            continue

        editor.status = status
        editor.stdscr = stdscr
        if extensions.dispatch_key(key):
            status = editor.status or ""
            continue

        # Handle file explorer keys when active
        if explorer.visible and explorer.active:
            # --- search mode: redirect all keys to the search buffer ---
            if explorer.searching:
                if key == "\x1b":  # Esc — exit search
                    explorer.exit_search()
                    status = ""
                    continue
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    explorer.search_query = explorer.search_query[:-1]
                    explorer.search(explorer.search_query)
                    status = f"/{explorer.search_query}" if explorer.search_query else ""
                    continue
                elif key in ("\n", "\r"):  # Enter — open selected result
                    selected = explorer.get_selected()
                    if selected:
                        depth, name, path, is_dir = selected
                        if path == "..":
                            pass  # ignore parent entry in search results
                        elif is_dir:
                            # Exit search and navigate tree to this folder.
                            explorer.exit_search()
                            # Expand every ancestor so the folder is visible.
                            p = os.path.dirname(path)
                            while p and p != explorer.root_dir:
                                explorer.expanded_dirs.add(p)
                                p = os.path.dirname(p)
                            explorer.expanded_dirs.add(path)
                            explorer.refresh()
                            explorer._select_path(path)
                            explorer.active = True
                            status = ""
                        else:
                            language, open_status = open_file_path(
                                stdscr, buf, explorer, path,
                                render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                            )
                            if open_status.startswith("Opened"):
                                buf.configure_for_language(language)
                                explorer.exit_search()
                                explorer.active = False
                                status = open_status
                            else:
                                status = open_status
                    continue
                elif key == curses.KEY_UP:
                    explorer.move_selection(-1)
                    continue
                elif key == curses.KEY_DOWN:
                    explorer.move_selection(1)
                    continue
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    explorer.search_query += key
                    explorer.search(explorer.search_query)
                    status = f"/{explorer.search_query}"
                    continue
                # swallow everything else during search
                continue
            if key == curses.KEY_UP:
                explorer.move_selection(-1)
                continue
            elif key == curses.KEY_DOWN:
                explorer.move_selection(1)
                continue
            elif key == "/":  # enter search mode
                explorer.enter_search()
                status = "/"
                continue
            elif key == curses.KEY_RIGHT:
                selected = explorer.get_selected()
                if selected and selected[3] and selected[2] not in explorer.expanded_dirs:
                    explorer.toggle_expand(explorer.selected_idx)
                continue
            elif key == curses.KEY_LEFT:
                selected = explorer.get_selected()
                if selected and selected[3] and selected[2] in explorer.expanded_dirs:
                    explorer.toggle_expand(explorer.selected_idx)
                elif explorer.can_go_up():
                    explorer.go_up()
                continue
            elif key in ("\n", "\r"):  # Enter - open file or toggle directory
                selected = explorer.get_selected()
                if selected:
                    depth, name, path, is_dir = selected
                    if path == "..":
                        explorer.go_up()
                    elif is_dir:
                        explorer.toggle_expand(explorer.selected_idx)
                    else:
                        # Open the file through the safe (dirty-guarded) path.
                        language, status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=lambda t: _draw_status_prompt(stdscr, t),
                        )
                        if status.startswith("Opened"):
                            buf.configure_for_language(language)
                            explorer.active = False  # hand focus to the editor
                        # On failure keep tree focus so the user can retry.
                continue
            elif key == "h":  # toggle hidden files in the tree
                explorer.toggle_hidden()
                continue
            elif key == "n":  # new file in the selected directory
                render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                name = _prompt_line(lambda: _get_key(stdscr), render, "New file name: ")
                if name:
                    path, error = explorer.create_file(name)
                    status = error or f"Created {name}"
                    if not error and name.startswith("."):
                        status += " (hidden — press h to show)"
                    if not error:
                        # Create-then-edit: open it straight away (the
                        # dirty-buffer guard inside still applies).
                        language, open_status = open_file_path(
                            stdscr, buf, explorer, path,
                            render_unsaved=render,
                        )
                        if open_status.startswith("Opened"):
                            buf.configure_for_language(language)
                            explorer.active = False
                            status = f"Created + opened {name}"
                        else:
                            status = f"Created {name} ({open_status})"
                continue
            elif key == "N":  # new folder in the selected directory
                render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                name = _prompt_line(lambda: _get_key(stdscr), render, "New folder name: ")
                if name:
                    _, error = explorer.create_folder(name)
                    status = error or f"Created folder {name}"
                    if not error and name.startswith("."):
                        status += " (hidden — press h to show)"
                continue
            elif key == "O":  # choose a project root via the system picker
                picked, info = filemanager.pick_folder(explorer.root_dir)
                if picked:
                    explorer.set_root(picked)
                    status = f"Project root: {picked}"
                elif info == "cancelled":
                    status = "Cancelled"
                elif info == "no system picker available":
                    # No desktop helper installed: fall back to typing a path.
                    render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                    typed = _prompt_line(lambda: _get_key(stdscr), render, "Project folder: ")
                    if typed:
                        target = os.path.expanduser(typed.strip())
                        if os.path.isdir(target):
                            explorer.set_root(target)
                            status = f"Project root: {target}"
                        else:
                            status = f"Not a directory: {target}"
                    else:
                        status = "Cancelled"
                else:
                    status = f"Folder picker failed: {info}"
                continue
            elif key == "R":  # reveal the tree root in the system file manager
                opened, info = filemanager.reveal_in_file_manager(explorer.root_dir)
                status = f"Opened in {info}" if opened else f"Reveal failed: {info}"
                continue
            elif key == "d":  # delete selected file/folder
                item = explorer.get_selected()
                if item:
                    _, _, path, is_dir = item
                    if path == "..":
                        status = "Cannot delete parent entry"
                    else:
                        render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                        name = os.path.basename(path)
                        kind = "folder" if is_dir else "file"
                        msg = f"Delete {kind} '{name}'? (y/n)"
                        if _yes_no_prompt(lambda: _get_key(stdscr), render, msg):
                            ok, msg = explorer.delete_selected()
                            status = msg
                            if ok and buf.filename and not os.path.exists(buf.filename):
                                buf.filename = None
                                buf.modified = False
                        else:
                            status = "Cancelled"
                continue
            elif key == "r":  # rename selected file/folder
                item = explorer.get_selected()
                if item:
                    _, _, path, _ = item
                    if path == "..":
                        status = "Cannot rename parent entry"
                    else:
                        render = lambda t: _draw_status_prompt(stdscr, t)  # noqa: E731
                        old_name = os.path.basename(path)
                        new_name = _prompt_line(
                            lambda: _get_key(stdscr), render,
                            f"Rename '{old_name}': ",
                        )
                        if new_name:
                            ok, msg = explorer.rename_selected(new_name)
                            status = msg
                        else:
                            status = "Cancelled"
                continue
            elif key == "y":  # yank/copy absolute path to clipboard
                path = explorer.copy_path()
                if path:
                    clipboard.sys_copy(path)
                    status = f"Copied: {path}"
                continue
            elif key == "Y":  # yank/copy relative path to clipboard
                path = explorer.copy_relative_path()
                if path:
                    clipboard.sys_copy(path)
                    status = f"Copied: {path}"
                continue
            elif key in ("\t", "\x05", "\x1b"):  # Tab / Ctrl-E / Esc -> editor
                explorer.active = False
                status = ""
                continue

        if explorer.visible and explorer.active and swallowed_by_tree(key):
            continue  # tree has focus: never leak typing into the editor

        # Handle git panel keys when active
        if git_panel and git_panel.visible and git_panel.active:
            if git_panel.mode == "diff" and diff_viewer:
                # Ctrl-G closes panel entirely from diff mode
                if key == "\x07":
                    git_panel.visible = False
                    git_panel.active = False
                    git_panel.end_diff()
                    diff_viewer.diff_text = ""
                    diff_viewer.lines = []
                    status = ""
                    continue
                # Route other keys to diff viewer
                if not diff_viewer_key(diff_viewer, key, text_height):
                    # q/Esc → exit diff mode
                    git_panel.end_diff()
                    diff_viewer.diff_text = ""
                    diff_viewer.lines = []
                    status = ""
                else:
                    status = ""
                continue
            if git_panel_key(git_panel, key):
                status = git_panel.last_result or ""
                continue
            # Tab/Esc from git panel → focus editor (Ctrl-G handled below)
            if key in ("\t", "\x1b"):
                git_panel.active = False
                status = ""
                continue

        if key == "\x07":  # Ctrl-G - toggle git panel
            if not git_panel:
                continue
            if not git_panel.visible:
                git_panel.visible = True
                git_panel.active = True
                git_panel.refresh()
                status = "Source Control (c:commit s:stage u:unstage d:diff)"
            elif not git_panel.active:
                git_panel.active = True
                status = ""
            else:
                git_panel.visible = False
                git_panel.active = False
                status = "Source Control closed"
            continue

        if sug.visible:
            if key in (curses.KEY_UP,):
                sug.move(-1)
                status = ""
                continue
            if key in (curses.KEY_DOWN,):
                sug.move(1)
                status = ""
                continue
            if key in ("\t", "\n", "\r"):
                suffix = sug.accept_suffix()
                sug.close()
                if suffix:
                    _insert_text(buf, suffix)
                    status = "Inserted suggestion"
                else:
                    status = ""
                ghost = None
                continue
            if key == "\x1b":
                sug.close()
                status = ""
                continue
        elif ghost is not None and (buf.cursor_y, buf.cursor_x) == ghost_anchor:
            if key == "\t":
                _insert_text(buf, ghost.text)
                status = "Accepted AI suggestion"
                ghost = None
                continue
            if key == "\x1b":
                ghost = None
                status = ""
                continue

        if key == "\x05":  # Ctrl-E - toggle explorer
            if not explorer.visible:
                # Hidden → show and activate
                explorer.visible = True
                explorer.active = True
                status = "Explorer opened (Esc to close, Enter to open file/folder)"
            else:
                # Visible but editor-focused → activate tree
                explorer.active = True
                status = ""
            continue
        if key == "\x1b" and explorer.visible and not explorer.active:
            # Esc from editor with tree visible → hide tree
            explorer.visible = False
            status = "Explorer closed"
            continue
        elif key == curses.KEY_RESIZE:
            continue
        elif key == "\x1b":  # ESC — check whether this is a bracketed paste
            stdscr.nodelay(True)
            peek = stdscr.getch()
            stdscr.nodelay(False)
            if peek != -1 and chr(peek) == "[":
                pasted = _read_bracketed_paste(stdscr)
                if pasted:
                    if buf.has_selection():
                        buf.delete_selection()
                    buf.paste(pasted)
                    status = f"Pasted {len(pasted)} chars"
            # else: plain ESC / unrecognized escape sequence — ignored for now
        elif key == "\x0f":  # Ctrl-O: Quick Open (fuzzy file search)
            if quick_open.visible:
                quick_open.close()
                stdscr.timeout(-1)
                status = ""
            else:
                quick_open.mode = "files"
                quick_open.open()
                stdscr.timeout(50)
                status = ""
        elif key == "\x06":  # Ctrl-F: find in buffer
            explorer.active = False
            _find_replace_prompt(stdscr, buf, mode="find",
                                 explorer_width=explorer_width)
        elif key == "\x12":  # Ctrl-R: replace all
            explorer.active = False
            result = _find_replace_prompt(stdscr, buf, mode="replace",
                                          explorer_width=explorer_width)
            if result:
                status = result
        elif key == "\x11":  # Ctrl-Q: quit (confirmation dialog)
            action = _confirm_quit_dialog(
                lambda: _get_key(stdscr),
                lambda ch, sel: _draw_quit_dialog(
                    stdscr, "Quit stdedit?",
                    ["You have unsaved changes."] if buf.modified
                    else ["There are no unsaved changes."],
                    ch, sel),
                bool(buf.modified), bool(buf.filename))
            if action in ("quit", "discard"):
                break
            if action == "save":
                try:
                    buf.save()
                    break
                except ValueError:
                    status = "No filename — cannot save"
                except OSError as exc:
                    status = f"Could not save: {exc}"
            else:
                status = ""
        elif key == "\x13":  # Ctrl-S
            try:
                buf.save()
                _last_save_time = time.time()
                status = f"Saved {buf.filename}"
            except ValueError:
                status = "No filename — run with a file argument to enable saving"
            except OSError as exc:
                status = f"Could not save: {exc}"
        elif key == "\x1a":  # Ctrl-Z undo
            status = "Undo" if buf.undo() else "Nothing to undo"
        elif key == "\x19":  # Ctrl-Y redo
            status = "Redo" if buf.redo() else "Nothing to redo"
        elif key == "\x01":  # Ctrl-A select all
            buf.select_all()
            selecting = False
            status = "Selected all"
        elif key == "\x00":  # Ctrl-Space: toggle selection mode
            selecting = not selecting
            if not selecting:
                buf.clear_selection()
            status = "Selection ON — move to select, Ctrl-Space again to stop" if selecting else "Selection OFF"
        elif key in ("\x18",):  # Ctrl-X cut
            text = buf.cut()
            selecting = False
            status = f"Cut {len(text)} chars" if text else "Nothing selected to cut"
        elif key == "\x03":  # Ctrl-C copy
            text = buf.copy()
            status = f"Copied {len(text)} chars" if text else "Nothing selected to copy"
        elif key == "\x16":  # Ctrl-V paste
            buf.paste()
            status = "Pasted" if buf.clipboard else "Clipboard empty"
        elif isinstance(key, str) and key in "([{":
            if buf.has_selection():
                buf.delete_selection()
            buf.auto_close_bracket(key)
        elif isinstance(key, str) and key in ")]}":
            if not buf.smart_dedent_on_char(key) and not buf.skip_closer(key):
                buf.insert_char(key)
        elif isinstance(key, str) and key in "\"'" and not buf.has_selection():
            # Quotes use the same lightweight auto-close path as brackets.
            if buf.cursor_x < len(buf.current_line) and buf.current_line[buf.cursor_x] == key:
                buf.cursor_x += 1
            else:
                buf._checkpoint_if_needed("insert_char")
                line = buf.current_line
                buf.lines[buf.cursor_y] = line[:buf.cursor_x] + key + key + line[buf.cursor_x:]
                buf.cursor_x += 1
                buf.modified = True
        elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            buf.backspace()
        elif key == curses.KEY_DC:
            buf.delete_char()
        elif key in ("\n", "\r"):
            buf.insert_newline()
        elif key == "\t":
            buf.insert_tab()
        elif key == curses.KEY_UP:
            buf.move_cursor(dy=-1, extend_selection=selecting)
        elif key == curses.KEY_DOWN:
            buf.move_cursor(dy=1, extend_selection=selecting)
        elif key == curses.KEY_LEFT:
            buf.move_cursor(dx=-1, extend_selection=selecting)
        elif key == curses.KEY_RIGHT:
            buf.move_cursor(dx=1, extend_selection=selecting)
        elif key == curses.KEY_HOME:
            buf.move_to(0, buf.cursor_y, extend_selection=selecting)
        elif key == curses.KEY_END:
            buf.move_to(len(buf.current_line), buf.cursor_y, extend_selection=selecting)
        elif isinstance(key, str) and key.isprintable():
            buf.insert_char(key)
        # anything else (unmapped function keys etc.) is ignored for now

        # Track last edit time for idle auto-save.
        if buf.modified and not _prev_modified:
            _last_edit_time = time.time()
            if settings.get("auto_save_on_edit"):
                saved, save_error = _auto_save_on_edit(buf)
                if saved:
                    _last_save_time = time.time()
                    status = "Auto-saved"
                elif save_error is not None:
                    status = f"Auto-save failed: {save_error}"

        # Keep the suggest popup & inline ghost in sync with the buffer.
        if not isinstance(key, tuple):
            fp = _lines_fingerprint(buf.lines)
            if fp != sug_fp:
                sug_fp = fp
                if isinstance(key, str) or key in (curses.KEY_BACKSPACE,
                                                   curses.KEY_DC):
                    ghost = None
                    last_buffer_change_at = time.monotonic()
                sug_words = suggest.identifier_words(buf.lines)
            start, prefix = suggest.word_at(buf.current_line, buf.cursor_x)
            if (settings.get("suggestions_on") and prefix
                    and not _in_double_quoted(buf)
                    and not (explorer.active or show_settings or show_help
                             or quick_open.visible or recent_picker.active
                             or image_view_active)):
                sug.open(language, sug_words, prefix)
            else:
                sug.close()


def line_number_width(line_count: int) -> int:
    """Return the number of columns needed for 1-indexed line numbers."""
    return max(2, len(str(max(1, line_count))))


def resolve_tree_root(filename, project_dir) -> str:
    """Decide which folder the file tree is rooted at.

    Precedence: explicit --project folder > opened file's parent > cwd.
    """
    if project_dir:
        return os.path.abspath(project_dir)
    if filename and os.path.isfile(filename):
        return os.path.dirname(os.path.abspath(filename))
    return "."


def _startup_tree(explorer: FileExplorer, filename) -> None:
    """Select *filename* in the tree so it is revealed on startup."""
    if filename and os.path.isfile(filename):
        explorer.reveal(filename)


def _draw_status_prompt(stdscr, text: str) -> None:
    """Render prompt text on the status row (used by interactive prompts)."""
    height, width = stdscr.getmaxyx()
    try:
        stdscr.addstr(height - 1, 0, _safe_render(text[: width - 1].ljust(width - 1)), curses.A_REVERSE)
        stdscr.refresh()
    except (curses.error, ValueError, UnicodeEncodeError):
        pass


def _find_all_matches(buf, query):
    """Return list of (line, start, end) for every occurrence of *query*."""
    q = query.lower()
    results = []
    for y in range(len(buf.lines)):
        line = buf.lines[y].lower()
        start = 0
        while True:
            pos = line.find(q, start)
            if pos < 0:
                break
            results.append((y, pos, pos + len(query)))
            start = pos + 1
    return results


def _find_replace_prompt(stdscr, buf, mode="find", explorer_width=25):
    """Modal find / replace prompt.  Renders the full editor on each keystroke
    so the user sees highlighted matches in real-time."""
    global _search
    _search["mode"] = mode
    _search["query"] = ""
    _search["replace"] = ""
    _search["matches"] = []
    _search["idx"] = 0
    _search["anchor"] = (buf.cursor_y, buf.cursor_x)
    _search["replacements"] = []

    field = "query"  # which field has focus: "query" or "replace"
    height, width = stdscr.getmaxyx()
    gutter_width = max(2, len(str(max(1, len(buf.lines))))) + 2
    text_width = max(1, width - explorer_width - gutter_width)
    text_height = height - 1

    def _render():
        """Redraw the full screen with match highlights and the prompt."""
        stdscr.erase()
        buf.update_scroll(text_height, text_width)
        for row in range(text_height):
            line_idx = buf.scroll_y + row
            _draw_gutter(stdscr, row, line_idx, len(buf.lines), gutter_width,
                         x_offset=explorer_width)
            if line_idx < len(buf.lines):
                _draw_line(stdscr, row, buf.lines[line_idx], buf.scroll_x,
                           text_width, schema.detect_language(buf.filename or ""),
                           x_offset=gutter_width + explorer_width)
                _highlight_selection(stdscr, row, line_idx, buf.lines[line_idx], buf,
                                     scroll_x=buf.scroll_x, width=text_width,
                                     x_offset=gutter_width + explorer_width)
                _highlight_find_match(stdscr, row, line_idx, text_width,
                                      buf.scroll_x, gutter_width + explorer_width)
        # Status prompt
        n = len(_search["matches"])
        pos = f" [{_search['idx'] + 1}/{n}]" if n else ""
        if field == "replace" or mode == "replace":
            label = "Replace" if field == "replace" else "Find"
            text = f" {label}: {_search[field]}{pos}"
        else:
            text = f" Find: {_search['query']}{pos}"
        try:
            stdscr.addstr(height - 1, 0, text[: width - 1].ljust(width - 1),
                          curses.A_REVERSE)
        except curses.error:
            pass
        stdscr.refresh()

    _render()
    while True:
        try:
            key = stdscr.get_wch()
        except curses.error:
            continue
        if isinstance(key, int):
            if key == curses.KEY_ENTER:
                key = "\n"
            elif key == curses.KEY_BACKSPACE:
                key = "\x7f"
            else:
                continue  # ignore other special keys
        if key == "\x1b":  # Esc — cancel
            # Undo any replacements made (walk backwards).
            for y, start, old_text, new_len in reversed(_search["replacements"]):
                line = buf.lines[y]
                buf.lines[y] = line[:start] + old_text + line[start + new_len:]
            buf.move_to(_search["anchor"][1], _search["anchor"][0])
            _search["query"] = ""
            _search["replace"] = ""
            _search["matches"] = []
            _search["idx"] = 0
            _search["anchor"] = None
            _search["replacements"] = []
            return
        if key == "\t":  # Tab — switch field (replace mode only)
            if mode == "replace":
                field = "replace" if field == "query" else "query"
                _render()
            continue
        if key in ("\n", "\r"):  # Enter
            if mode == "replace" and field == "query":
                # Move to replace field.
                field = "replace"
                _render()
                continue
            if mode == "replace" and _search["matches"]:
                # Replace ALL matches.
                for m_line, m_start, m_end in _search["matches"]:
                    old_text = buf.lines[m_line][m_start:m_end]
                    new_len = len(_search["replace"])
                    _search["replacements"].append((m_line, m_start, old_text, new_len))
                    buf.lines[m_line] = (buf.lines[m_line][:m_start]
                                         + _search["replace"]
                                         + buf.lines[m_line][m_end:])
                buf.modified = True
                count = len(_search["replacements"])
                _search["query"] = ""
                _search["replace"] = ""
                _search["matches"] = []
                _search["idx"] = 0
                _search["anchor"] = None
                _search["replacements"] = []
                return f"Replaced {count} occurrences"
            # Find mode: confirm and close.
            _search["query"] = ""
            _search["replace"] = ""
            _search["matches"] = []
            _search["idx"] = 0
            _search["anchor"] = None
            _search["replacements"] = []
            return
        if key == "\x06":  # Ctrl-F — next match
            if _search["matches"]:
                _search["idx"] = (_search["idx"] + 1) % len(_search["matches"])
                ml, ms, me = _search["matches"][_search["idx"]]
                buf.move_to(ms, ml)
                _render()
            continue
        if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            target = _search[field]
            if target:
                _search[field] = target[:-1]
                if field == "query" and _search["query"]:
                    _search["matches"] = _find_all_matches(buf, _search["query"])
                    _search["idx"] = 0
                    if _search["matches"]:
                        ml, ms, me = _search["matches"][0]
                        buf.move_to(ms, ml)
                _render()
            continue
        if isinstance(key, str) and len(key) == 1 and key.isprintable():
            _search[field] += key
            if field == "query":
                _search["matches"] = _find_all_matches(buf, _search["query"])
                _search["idx"] = 0
                if _search["matches"]:
                    ml, ms, me = _search["matches"][0]
                    buf.move_to(ms, ml)
            _render()
            continue


# ---------------------------------------------------------------------- #
# Help overlay (Ctrl-H / F1)
# ---------------------------------------------------------------------- #
HELP_SECTIONS = [
    ("EDITING", [
        "characters          type to insert text at the cursor",
        "Enter               new line (auto-indents per language)",
        "Tab                 indent (width adapts to the language)",
        "Backspace / Del     delete character",
        "< > ^ v             move cursor",
        "Home / End          jump to line start / end",
        "( { [               auto-close bracket pairs",
        ") } ]               skip closer / dedent on block close",
        "\" '                auto-close quotes",
        "Ctrl-F              find text in the file",
        "Ctrl-R              replace all occurrences",
    ]),
    ("SELECTION & CLIPBOARD", [
        "Ctrl-A              select all",
        "Ctrl-Space          start / stop selection ([SELECT] in status)",
        "(arrow keys extend the selection while it is active)",
        "Ctrl-C              copy selection",
        "Ctrl-X              cut selection",
        "Ctrl-V              paste (system + internal clipboard)",
    ]),
    ("HISTORY & FILES", [
        "Ctrl-Z              undo",
        "Ctrl-Y              redo",
        "Ctrl-S              save current file",
        "Ctrl-P              settings / preferences",
        "Ctrl-O              quick open — fuzzy file search",
        "F5  /  Ctrl-Enter   run current file in a terminal (r rerun, Enter close)",
        "Ctrl-Q              quit (opens a confirmation dialog)",
    ]),
    ("FILE TREE (Ctrl-E panel)", [
        "Ctrl-E              open / focus the file tree",
        "^ v                 move selection",
        "< >                 collapse / expand folder (<..> climbs up)",
        "Enter               open file / expand folder / go up on <..>",
        "/                   search files and folders (Esc to cancel)",
        "Esc                 close the file tree",
        "h                   show / hide dotfiles",
        "n                   new file (opens it for editing)",
        "N                   new folder in selected folder",
        "d                   delete file / folder (with confirmation)",
        "r                   rename file / folder",
        "y                   copy absolute path to clipboard",
        "Y                   copy relative path to clipboard",
        "O                   pick project root via system dialog",
        "R                   reveal root in system file manager",
        "Tab / Esc           focus the editor",
    ]),
    ("GIT STATUS", [
        "status bar          shows branch name and change counts",
        "                    +N added  ~N modified  -N deleted  !N untracked",
        "automatic           refreshes every 2 seconds (no manual trigger)",
    ]),
    ("SOURCE CONTROL (Ctrl-G panel)", [
        "Ctrl-G              open / close source control panel",
        "Up / Down           move selection",
        "c                   focus commit message box",
        "Enter               commit (when message box focused)",
        "Esc                 cancel commit / defocus panel",
        "s                   stage selected file",
        "u                   unstage selected file",
        "S                   stage all changes",
        "U                   unstage all changes",
        "d                   show diff for selected file",
        "p                   push",
        "P                   pull",
        "R                   refresh status",
        "b                   switch branch",
        "I                   list issues (o:close r:reopen)",
        "M                   list PRs (c:checkout m:merge)",
        "Tab / Ctrl-G / Esc  focus the editor",
    ]),
    ("DIFF VIEWER", [
        "d / Space           page down",
        "u                   page up",
        "Up / Down           scroll one line",
        "g / G               jump to top / bottom",
        "q / Esc             close diff view",
    ]),
    ("SETTINGS (Ctrl-P panel)", [
        "Ctrl-P              open / close settings panel",
        "Up / Down           navigate settings (section headers too)",
        "Space / Enter       toggle a setting, or expand/collapse a section",
        "▸ / ▾               collapsed / expanded section header",
        "click header        expand / collapse a section",
        "click setting       select it (Space to toggle)",
        "q / Esc / Ctrl-P    close settings panel",
    ]),
    ("MOUSE", [
        "click               position cursor",
        "double-click        select word",
        "triple-click        select line",
        "drag                select text",
        "Shift+click         extend selection",
        "scroll wheel        scroll up / down",
    ]),
    ("TERMINAL & PROMPTS", [
        "terminal paste      bracketed paste inserts multi-line text",
        "typed prompts       Enter confirms, Esc cancels",
        "prompt Tab          autocomplete file paths",
        "prompt Backspace    edits the text (new file/folder, O fallback)",
        "icons               Nerd Font glyphs (e.g. MesloLGS NF);",
        "                    disable with STDEDIT_ICONS=0",
        "",
        "(prompts appear for n / O and the O path fallback)",
    ]),
    ("HELP", [
        "Ctrl-H or F1        open / close this guide",
        "Up / Down, PgUp/Dn  scroll this guide",
        "q / Esc / Enter     close this guide",
    ]),
]


def build_help_lines(width):
    """Pure helper: help overlay content fitted to `width` columns."""
    out = []
    limit = max(10, int(width))
    for title, entries in HELP_SECTIONS:
        out.append(title)
        sep = "\u2550" * min(len(title), limit - 2)
        out.append(sep)
        for entry in entries:
            out.append("  " + entry)
        out.append("")
    return [line[:limit] for line in out]


def is_help_toggle(key, tree_active):
    """Should `key` open/close the help overlay?

    Raw Ctrl-H (\\x08) and F1 work anywhere.
    """
    return key == "\x08" or key == curses.KEY_F1


def _run_current_file(buf) -> str:
    """Open the current file in an external terminal and run it.

    Auto-saves unsaved edits first (quietly), then delegates to
    ``runner.run_file``.  Returns the status-bar text (success or reason).
    """
    if not buf.filename:
        return "Nothing to run — open or save a file first"
    if buf.modified:
        try:
            buf.save()
        except OSError as exc:
            return f"Could not save before running: {exc}"
    ok, msg = runner.run_file(buf.filename)
    return msg


def swallowed_by_tree(key) -> bool:
    """Should `key` be swallowed while the file tree has focus?

    Only printable single characters: anything else that reaches this
    point is either a control key with a legitimate global action
    (Ctrl-S save, Ctrl-Q quit, ...) or an editing key that the editor
    branch must keep handling.  Without this guard, typing while the
    tree is focused silently inserts characters into the document.
    """
    return isinstance(key, str) and len(key) == 1 and key.isprintable()


def clamp_scroll(offset, delta, total, view_h):
    """New scroll offset after moving `delta` rows, clamped to content.

    Keeps the viewport inside [0, max(total - view_h, 0)] so the guide
    can never scroll past its own text on any terminal size.
    """
    if total <= 0 or view_h <= 0:
        return 0
    return max(0, min(offset + delta, max(total - view_h, 0)))


_MIN_HELP_W = 50


def _draw_help_overlay(stdscr, lines, offset=0):
    """Paint a centered bordered help box over the current frame.

    `offset` scrolls through `lines` when they exceed the terminal
    height; ▲/▼ corner markers signal hidden content above/below.
    """
    height, width = stdscr.getmaxyx()
    content_w = max([len(l) for l in lines] or [20])
    inner_w = max(_MIN_HELP_W, min(content_w + 6, width * 70 // 100))
    inner_w = min(inner_w, width - 2)
    body_h = len(lines)
    view_h = max(1, min(body_h, height - 2))
    box_h = view_h + 2
    top = max(0, (height - box_h) // 2)
    left = max(0, (width - inner_w) // 2)

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, text[:width - col], attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass

    title = " stdedit help - q/Esc/Enter close \u00b7 arrows scroll "
    max_title_w = inner_w - 2
    if len(title) > max_title_w:
        title = title[:max_title_w - 3] + "... "
    fill = max(max_title_w - len(title), 0)
    left_fill = fill // 2
    right_fill = fill - left_fill
    put(top, left, "\u250c" + "\u2500" * left_fill + title + "\u2500" *
        right_fill + "\u2510", curses.A_REVERSE)
    for i in range(view_h):
        text = lines[offset + i] if offset + i < body_h else ""
        put(top + 1 + i, left, "\u2502" + " " * inner_w + "\u2502")
        stripped = text.rstrip()
        if stripped and all(c == "\u2550" for c in stripped):
            attr = curses.A_BOLD
        elif stripped and not stripped.startswith(" "):
            attr = curses.A_BOLD
        else:
            attr = 0
        put(top + 1 + i, left + 2, stripped, attr)
    put(top + box_h - 1, left,
        "\u2514" + "\u2500" * (inner_w - 2) + "\u2518")
    # Scroll indicators: ▲ above, ▼ below.
    if offset > 0:
        put(top, left + inner_w - 1, "\u25b2", curses.A_REVERSE)
    if offset + view_h < body_h:
        put(top + box_h - 1, left + inner_w - 1, "\u25bc",
            curses.A_REVERSE)


# ------------------------------------------------------------------ #
# Auto-suggest (popup + inline ghost text)
# ------------------------------------------------------------------ #


def _insert_text(buf, text: str) -> None:
    """Insert possibly multi-line *text* at the cursor (one checkpoint)."""
    if not text:
        return
    buf._checkpoint_if_needed("inline_suggest")
    x0 = buf.cursor_x
    original_tail = buf.lines[buf.cursor_y][x0:]
    parts = text.split("\n")
    if len(parts) == 1:
        buf.lines[buf.cursor_y] = (buf.lines[buf.cursor_y][:x0]
                                   + parts[0] + original_tail)
        buf.cursor_x = x0 + len(parts[0])
    else:
        buf.lines[buf.cursor_y] = buf.lines[buf.cursor_y][:x0] + parts[0]
        for i in range(1, len(parts)):
            row = parts[i] if i < len(parts) - 1 else parts[i] + original_tail
            buf.lines.insert(buf.cursor_y + i, row)
        buf.cursor_y += len(parts) - 1
        buf.cursor_x = len(parts[-1])
    buf._set_content_chars(buf._content_chars + len(text))
    buf.modified = True


def _draw_suggest_overlay(stdscr, sug, buf, left_offset, gutter_width,
                          text_width, height, width) -> None:
    """Draw the auto-suggest popup anchored near the cursor (or above it)."""
    items = sug.candidates
    if not items:
        return
    show = len(items)
    inner_w = max(26, min(40, max(0, width // 3)))
    cursor_row = buf.cursor_y - buf.scroll_y
    cursor_col = left_offset + gutter_width + (buf.cursor_x - buf.scroll_x)
    box_h = show + 2
    top = cursor_row + 1
    if top + box_h > height - 1:
        top = max(0, cursor_row - box_h)
    left = min(max(0, cursor_col), max(0, width - inner_w - 1))

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, _safe_render(text)[:width - col], attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass

    put(top, left, "\u250c" + "\u2500" * (inner_w - 1) + "\u2510", curses.A_REVERSE)
    for i, item in enumerate(items):
        sel = (i == sug.selected)
        label = ("\u25b6 " if sel else "  ") + item
        attr = curses.A_REVERSE if sel else 0
        put(top + 1 + i, left, (label + " " * inner_w)[:inner_w + 1], attr)
    hint = " Tab/Enter accept  Esc close "
    pad = inner_w - 1 - len(hint)
    if pad >= 0:
        line = ("\u2514" + "\u2500" * max(0, pad // 2) + hint
                + "\u2500" * (pad - pad // 2) + "\u2518")
    else:
        line = "\u2514" + hint[:max(0, inner_w - 1)] + "\u2518"
    put(top + show + 1, left, line)


def _draw_ghost(stdscr, buf, ghost, left_offset, gutter_width, text_width) -> None:
    """Render dim inline-suggestion text immediately after the cursor."""
    if buf.cursor_y != ghost.range_start_y or buf.cursor_x != ghost.range_start_x:
        return
    if buf.cursor_x < len(buf.current_line):
        return
    row = buf.cursor_y - buf.scroll_y
    col = left_offset + gutter_width + (buf.cursor_x - buf.scroll_x)
    if col < 0:
        return
    first = ghost.text.split("\n", 1)[0]
    avail = max(0, text_width - (buf.cursor_x - buf.scroll_x))
    slice_text = first[:avail]
    if not slice_text:
        return
    try:
        stdscr.addstr(row, col, _safe_render(slice_text), curses.A_DIM)
    except (curses.error, ValueError, UnicodeEncodeError):
        pass


def _in_double_quoted(buf) -> bool:
    """True if the cursor sits inside a double-quoted string.

    Escape-aware scan of the lines before the cursor plus the current
    line's prefix.  Tracks the opening quote kind ('"' or "'") so a
    double quote inside a single-quoted string does not count.  Triple
    quotes flip parity like single ones (a '''…''' docstring reads as
    inside).  Comments containing quotes may mislead by design.
    """
    inside: str | None = None  # None | '"' | "'"
    escaped = False

    def scan(iterable):
        nonlocal inside, escaped
        for ch in iterable:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif inside is None:
                if ch in ('"', "'"):
                    inside = ch
            elif ch == inside:
                inside = None

    for row in range(buf.cursor_y):
        scan(buf.lines[row])
    scan(buf.lines[buf.cursor_y][:buf.cursor_x])
    return inside == '"'


def _ghost_wanted(buf) -> bool:
    """True when an inline suggestion makes sense at the cursor."""
    if _in_double_quoted(buf):
        return False
    line = buf.current_line
    x = buf.cursor_x
    if x == 0:
        return True
    if x >= len(line):
        return True
    prev = line[x - 1]
    return not (prev.isalnum() or prev == "_")


def _lines_fingerprint(lines) -> tuple:
    """Cheap digest to detect edits inside the scannable window."""
    n = min(len(lines), suggest.DOC_SCAN_LIMIT)
    total = 0
    for i in range(n):
        total += len(lines[i])
    return (len(lines), total)


def _fetch_ghost_text(buf) -> "object | None":
    """Fetch an inline suggestion for the buffer (test hook honored)."""
    fake = os.environ.get("STDEDIT_FAKE_GHOST")
    if fake is not None:
        if fake == "none":
            return None
        if buf is None:
            return codeium.Completion(fake)
        return codeium.Completion(fake, buf.cursor_y, buf.cursor_x)
    key = codeium.get_api_key()
    if not key:
        return None
    return codeium.get_completion(
        buf.lines, buf.cursor_y, buf.cursor_x, buf.filename or "", key)


class RecentPicker:
    """Modal recent-files list for the dashboard.

    ``open()`` snapshots the current recent files — most recent first,
    paths that no longer exist filtered out, capped at ``MAX_ENTRIES``.
    The TUI renders it as a bordered overlay and opens ``selected_path``
    on Enter.
    """

    MAX_ENTRIES = 10

    def __init__(self) -> None:
        self.active = False
        self.entries: list[str] = []
        self.selected = 0

    def open(self) -> None:
        self.entries = [
            p for p in recent.get_recent()
            if p and os.path.isfile(p)
        ][: self.MAX_ENTRIES]
        self.selected = 0
        self.active = True

    def close(self) -> None:
        self.active = False

    def selected_path(self) -> str | None:
        if 0 <= self.selected < len(self.entries):
            return self.entries[self.selected]
        return None

    def move_selection(self, dy: int) -> None:
        if self.entries:
            self.selected = max(0, min(self.selected + dy, len(self.entries) - 1))


def _draw_recent_overlay(stdscr, picker: RecentPicker, height: int, width: int) -> None:
    """Paint the bordered recent-files picker overlay."""
    items = picker.entries
    inner_w = max(40, min(72, width * 70 // 100))
    inner_w = min(inner_w, width - 2)
    view_h = max(1, min(len(items) or 1, max(1, height - 7)))
    box_h = view_h + 5  # title + header + separator + items + footer + border
    top = max(0, (height - box_h) // 2)
    left = max(0, (width - inner_w) // 2)

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, _safe_render(text)[:width - col], attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass

    put(top, left, "\u250c" + " RECENT FILES ".center(inner_w - 2)[:inner_w - 2]
        + "\u2510", curses.A_REVERSE)
    put(top + 1, left, "\u2502", curses.A_DIM)
    put(top + 1, left + 1, f" {len(items)} recent file(s) "
        + " " * max(0, inner_w - 2 - len(f" {len(items)} recent file(s) ")),
        curses.A_DIM)
    put(top + 1, left + inner_w - 1, "\u2502", curses.A_DIM)
    sep = "\u251c" + "\u2500" * max(0, inner_w - 2) + "\u2524"
    put(top + 2, left, sep, curses.A_DIM)
    offset = 0
    if items:
        offset = min(max(picker.selected - (view_h - 1), 0),
                     max(len(items) - view_h, 0))
    for i in range(view_h):
        index = offset + i
        if index < len(items):
            text = items[index]
            attr = curses.A_REVERSE if index == picker.selected else 0
        else:
            text = "No recent files" if not items else ""
            attr = 0
        put(top + 3 + i, left, "\u2502", curses.A_DIM)
        put(top + 3 + i, left + 1,
            " " + text[:inner_w - 3]
            + " " * max(0, inner_w - 3 - min(len(text), inner_w - 3)), attr)
        put(top + 3 + i, left + inner_w - 1, "\u2502", curses.A_DIM)
    bottom = top + box_h - 1
    put(top + 3 + view_h, left + 1,
        " \u2191/\u2193 select \u2192 Enter open \u2192 Esc back", curses.A_DIM)
    put(bottom, left, "\u2514" + "\u2500" * max(0, inner_w - 2) + "\u2518", curses.A_DIM)


def _quick_open_geometry(qo: QuickOpen, height: int, width: int) -> tuple:
    """Shared Quick Open box geometry for drawing AND terminal-caret math."""
    items = qo.get_display_items(limit=max(1, height - 6))
    inner_w = max(40, min(60, width * 60 // 100))
    inner_w = min(inner_w, width - 2)
    total = len(items)
    view_h = max(1, min(total, height - 6))
    box_h = view_h + 5  # title + input + separator + items + hint + bottom
    top = max(0, (height - box_h) // 2)
    left = max(0, (width - inner_w) // 2)
    return items, top, left, inner_w, view_h, box_h


def _quick_open_cursor_col(qo: QuickOpen, height: int, width: int) -> tuple[int, int]:
    """(row, col) of the ``|`` caret inside the search input box.

    The caret sits on the input row, immediately after whatever has been
    typed (a bare ``|`` when the query is empty), so the block cursor is
    visible inside the box instead of a hidden editor position.
    """
    _, top, left, inner_w, _, _ = _quick_open_geometry(qo, height, width)
    col = left + 2 + min(len(qo.query), inner_w - 3)
    return top + 1, col


_qo_last_rect: tuple[int, int, int, int] | None = None


def _draw_quick_open_overlay(stdscr, qo: QuickOpen) -> None:
    """Paint a centered bordered quick-open box over the current base frame.

    The input row embeds a ``|`` caret right after the typed text, a dim
    divider separates it from the results, a hint row lists the keys, and
    the bottom border is clipped by ``put`` so it can never run off-screen.

    When the result count changes the box relocates (size/centre shift), so
    the previously drawn rectangle is erased as well: cursors-only redraws
    never blank old cells, which would otherwise leave ghost pixels behind.
    """
    global _qo_last_rect
    height, width = stdscr.getmaxyx()
    items, top, left, inner_w, view_h, box_h = _quick_open_geometry(
        qo, height, width)

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, text[:width - col], attr)
        except curses.error:
            pass

    # Erase the old box location (and the new one) before repainting so a
    # shrinking or moving box never leaves stale cells on screen.
    eraser = " " * inner_w
    for rtop, rleft, rinner_w, rbox_h in ((top, left, inner_w, box_h),
                                          *((_qo_last_rect,) if _qo_last_rect else ())):
        for row in range(rtop, min(rtop + rbox_h, height)):
            put(row, rleft, eraser[:rinner_w])
    _qo_last_rect = (top, left, inner_w, box_h)

    # Title
    folder_mode = qo.mode == "folders"
    title = " Open Folder " if folder_mode else " Open File "
    put(top, left, "\u250c" + title.center(inner_w - 2)[:inner_w - 2] + "\u2510",
        curses.A_REVERSE)
    # Input line: the vertical-bar caret comes immediately after the typed
    # text, inside the box (a bare `|` when the query is empty).
    put(top + 1, left, "\u2502", curses.A_DIM)
    caret = qo.query + "|"
    if len(caret) > inner_w - 2:
        caret = caret[: inner_w - 2]
    text = " " + caret
    padding = max(0, inner_w - 2 - len(text))
    put(top + 1, left + 1, text + " " * padding, curses.A_UNDERLINE)
    put(top + 1, left + inner_w - 1, "\u2502", curses.A_DIM)
    # Separator
    put(top + 2, left, "\u251c" + "\u2500" * (inner_w - 2) + "\u2524",
        curses.A_DIM)
    # Items (or a status/hint message while there are no results)
    kind_raw = "folders" if folder_mode else "files"
    if not items:
        row = top + 3
        if qo.query:
            if qo.loading:
                msg = f" Searching...  ({len(qo.files)} {kind_raw} indexed)"
            elif qo.scan_error:
                msg = f" Search error: {qo.scan_error}"
            elif qo.capped:
                msg = f" Index capped (40k {kind_raw}) — type more specifically"
            elif qo.scoring:
                msg = " Updating results..."
            else:
                if folder_mode:
                    direct = qo._direct_folder()
                else:
                    direct = qo._direct_candidate()
                if direct:
                    msg = (" Press Enter to open this folder as project root"
                           if folder_mode else " Press Enter to open typed path")
                elif not folder_mode and qo._direct_folder():
                    msg = " Press Enter to open this folder as project root"
                else:
                    msg = " No matches"
            put(row, left + 1, msg, curses.A_DIM)
        else:
            empty_hint = (f" Type to search {kind_raw}..." if folder_mode
                          else f" Recent {kind_raw}" if qo.show_recent_on_empty
                          else f" Type to search {kind_raw}...")
            put(row, left + 1, empty_hint, curses.A_DIM)
    else:
        for i, (display_path, is_sel) in enumerate(items[:view_h]):
            # Show just the path relative to root if possible
            short = display_path
            if short.startswith(qo.root_dir):
                short = short[len(qo.root_dir):]
                if short.startswith("/"):
                    short = short[1:]
            if folder_mode:
                short = short + "/"
            # Truncate if too long
            avail = inner_w - 4
            if len(short) > avail:
                short = "..." + short[-(avail - 3):]
            marker = "\u25b6 " if is_sel else "   "
            attr = curses.A_REVERSE if is_sel else 0
            pad = max(0, inner_w - 2 - len(marker) - len(short))
            put(top + 3 + i, left + 1,
                (marker + short + " " * pad)[:inner_w - 2], attr)
    # Hint row
    hint = " \u2191/\u2193 select \u2192 Enter open \u2192 Esc back"
    pad = max(0, inner_w - 2 - len(hint))
    put(top + 3 + view_h, left + 1, hint + " " * pad, curses.A_DIM)
    # Bottom border
    put(top + box_h - 1, left,
        "\u2514" + "\u2500" * (inner_w - 2) + "\u2518")


def _draw_settings_overlay(stdscr, selected_idx: int, panel_width: int,
                           expanded: dict[str, bool]) -> None:
    """Draw settings as a left sidebar panel (same style as file tree).

    Each section is a dropdown: a header row that expands/collapses the
    setting rows underneath it.
    """
    height, width = stdscr.getmaxyx()
    draw_height = height - 1  # -1 for status bar
    rows, start_idx = _settings_display_layout(expanded, selected_idx,
                                               draw_height)

    # Draw right border
    for row in range(height):
        try:
            stdscr.addstr(row, panel_width - 1, "\u2502", curses.A_DIM)
        except curses.error:
            pass

    # Draw items
    for i, row in enumerate(rows[start_idx:start_idx + draw_height]):
        if row[0] == "header":
            _, label, lbl_idx = row
            collapsed = not expanded.get(label, False)
            arrow = "\u25b8" if collapsed else "\u25be"
            display = f" {arrow} {label}"
            attr = curses.A_BOLD
            if lbl_idx == selected_idx:
                attr |= curses.A_REVERSE
        elif row[0] == "separator":
            display = "\u2550" * (panel_width - 1)
            attr = curses.A_DIM
        elif row[0] == "gap":
            display = ""
            attr = 0
        elif row[0] == "item":
            _, key, label, on, nav_i = row
            if settings.is_radio_key(key):
                marker = "(x)" if on else "( )"
            else:
                marker = "[x]" if on else "[ ]"
            display = f"  {marker} {label}"
            attr = curses.A_REVERSE if nav_i == selected_idx else 0
        else:
            continue
        try:
            stdscr.addstr(i, 0, display.ljust(panel_width - 1)[:panel_width - 1], attr)
        except curses.error:
            pass

    # Hint at bottom of panel
    hint = " Ctrl-P close"
    try:
        stdscr.addstr(height - 2, 0, hint[:panel_width - 1], curses.A_DIM)
    except curses.error:
        pass


# ---------------------------------------------------------------------- #
# Prompts (testable: they take read_key/render callables, not raw curses)
# ---------------------------------------------------------------------- #
def _get_key(stdscr):
    """Read one key with curses keypad-Enter normalized to "\\n".

    With keypad(True) enabled, real terminals report the physical Enter
    key as curses.KEY_ENTER rather than "\\n"/"\\r".  Normalizing here
    means every consumer (main loop, tree handler, prompts) sees a plain
    newline.  Returns None when curses reports no readable input.
    """
    try:
        key = stdscr.get_wch()
    except curses.error:
        return None
    if key == curses.KEY_ENTER:
        return "\n"
    if key == curses.KEY_MOUSE:
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return None
        return ("__mouse__", mx, my, bstate)
    return key


def _unsaved_changes_prompt(read_key, render=None) -> str:
    """Ask what to do about unsaved changes. Returns 'save'|'discard'|'cancel'."""
    if render is not None:
        render("Unsaved changes — (s)ave, (d)iscard, (c)ancel?")
    while True:
        try:
            k = read_key()
        except curses.error:
            continue
        if isinstance(k, str):
            if k in ("s", "S"):
                return "save"
            if k in ("d", "D"):
                return "discard"
            if k in ("c", "C", "\x1b"):
                return "cancel"


def _yes_no_prompt(read_key, render, message) -> bool:
    """Single-question confirm. y/Enter -> True; n/Esc -> False.

    Any other key re-prompts, mirroring the unsaved-changes flow.
    """
    if render is not None:
        render(message)
    while True:
        try:
            k = read_key()
        except curses.error:
            continue
        if isinstance(k, str):
            if k in ("y", "Y", "\n", "\r"):
                return True
            if k in ("n", "N", "\x1b"):
                return False


def _leave_to_dashboard(stdscr, buf, render_unsaved=None) -> tuple[bool, str]:
    """Return ``(True, "")`` when switching into dashboard mode is allowed.

    A dirty document is run through the project's existing
    Save / Discard / Cancel policy first; ``cancel`` keeps the editor where
    it is.  Abandoning a clean (or just-saved) buffer is allowed.
    """
    if buf.modified:
        choice = _unsaved_changes_prompt(
            lambda: _get_key(stdscr),
            render_unsaved or (lambda t: _draw_status_prompt(stdscr, t)),
        )
        if choice == "save":
            try:
                buf.save()
            except ValueError:
                return False, "No filename — cannot save"
            except OSError as exc:
                return False, f"Could not save: {exc}"
        elif choice == "cancel":
            return False, "Cancelled"
    return True, ""


def _quit_dialog_choices(modified: bool, can_save: bool) -> list[tuple[str, str]]:
    """Return the quit-dialog buttons as ``(label, action)`` pairs.

    ``Cancel`` is always last so the default (focused) button is safe.
    Actions: "quit" | "discard" | "save" | "cancel".
    """
    if not modified:
        return [("Quit", "quit"), ("Cancel", "cancel")]
    if can_save:
        return [("Save & Quit", "save"), ("Discard & Quit", "discard"),
                ("Cancel", "cancel")]
    return [("Discard & Quit", "discard"), ("Cancel", "cancel")]


def _quit_dialog_step(key, selected: int, choices: list[tuple[str, str]]):
    """Map a dialog key to ``(new_selected, action_or_None)``.

    Left/Right/Tab move the focus; Enter/Space pick the focused button;
    Esc/n cancels; s/d/q/y are direct shortcuts.
    """
    n = len(choices)
    if key == curses.KEY_LEFT:
        return (selected - 1) % n, None
    if key in (curses.KEY_RIGHT, "\t"):
        return (selected + 1) % n, None
    if key in ("\n", "\r", " "):
        return selected, choices[selected][1]
    if key in ("\x1b", "n", "N"):
        return selected, "cancel"
    if key in ("s", "S"):
        actions = [a for _, a in choices]
        if "save" in actions:
            return selected, "save"
    if key in ("d", "D", "q", "Q", "y", "Y"):
        return selected, "discard" if any(a == "discard" for _, a in choices) else "quit"
    return selected, None


def _confirm_quit_dialog(read_key, render, modified: bool,
                         can_save: bool) -> str:
    """Quit-confirmation dialog loop. Returns "quit"|"discard"|"save"|"cancel".

    ``render`` receives ``(choices, selected)`` each frame; callers wrap a
    ``_draw_quit_dialog`` invocation so the dialog is fully unit-testable
    without a terminal.
    """
    choices = _quit_dialog_choices(modified, can_save)
    selected = len(choices) - 1  # default focus: Cancel
    render(choices, selected)
    while True:
        try:
            k = read_key()
        except curses.error:
            continue
        selected, action = _quit_dialog_step(k, selected, choices)
        if action is not None:
            return action
        render(choices, selected)


def _draw_quit_dialog(stdscr, title: str, body: list[str],
                      choices: list[tuple[str, str]], selected: int) -> None:
    """Paint a centered bordered quit-confirmation box.

    ``choices`` are ``(label, action)``; the focused button is highlighted
    with reverse video and the rest are drawn bold.
    """
    height, width = stdscr.getmaxyx()
    labels = [f"[ {label} ]" for label, _ in choices]
    button_line = "   ".join(labels)
    content_w = max([len(t) for t in body or [""]] + [len(button_line)])
    inner_w = max(len(title) + 2, content_w)   # interior width between borders
    inner_w = min(inner_w + 2, width - 3)
    if len(title) > inner_w - 2:
        title = title[:inner_w - 5] + "..."
    box_h = len(body) + 4  # title, body, spacer, button-row, bottom
    top = max(0, (height - box_h) // 2)
    left = max(0, (width - inner_w) // 2 - 1)

    def put(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, _safe_render(text)[:width - col], attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass

    fill = max(inner_w - len(title) - 2, 0)
    put(top, left, "\u250c" + title + "\u2500" * fill + "\u2510",
        curses.A_REVERSE)
    for i, line in enumerate(body):
        put(top + 1 + i, left,
            "\u2502" + line.ljust(inner_w)[:inner_w] + "\u2502")
    put(top + 1 + len(body), left, "\u2502" + " " * inner_w + "\u2502")
    x = left + 1 + max(0, (inner_w - len(button_line)) // 2)
    for i, label in enumerate(labels):
        attr = curses.A_REVERSE if i == selected else curses.A_BOLD
        put(top + len(body) + 1, x, label, attr)
        x += len(label) + 3
    put(top + box_h - 1, left, "\u2514" + "\u2500" * inner_w + "\u2518")


def _prompt_line(read_key, render, title: str = "Open file: ") -> Optional[str]:
    """Minimal single-line prompt with tab completion. Returns entered text or None."""
    text = ""
    while True:
        render(title + text)
        try:
            k = read_key()
        except curses.error:
            continue
        if k in ("\n", "\r"):
            return text.strip() or None
        if k == "\x1b":
            return None
        if k in ("\x7f", "\b", curses.KEY_BACKSPACE):
            text = text[:-1]
        elif k == "\t":  # Tab completion
            matches = completion.complete_path(text)
            if len(matches) == 1:
                text = matches[0]
            elif len(matches) > 1:
                text = completion.common_prefix(matches)
        elif isinstance(k, str) and k.isprintable():
            text += k


def open_file_path(stdscr, buf: Buffer, explorer: Optional[FileExplorer], path: str, render_unsaved=None) -> Tuple[str, str]:
    """Safely open `path` into the buffer.

    Guards against losing unsaved changes (save/discard/cancel prompt),
    reloads the file, re-detects its language and re-roots/highlights the
    explorer at the file's parent folder. Returns (language, status_text).
    """
    current_language = schema.detect_language(buf.filename or "")
    if buf.modified:
        choice = _unsaved_changes_prompt(lambda: _get_key(stdscr), render_unsaved)
        if choice == "save":
            try:
                buf.save()
            except ValueError:
                return current_language, "No filename — cannot save; open cancelled"
            except OSError as exc:
                return current_language, f"Could not save; open cancelled: {exc}"
        elif choice != "discard":
            return current_language, "Open cancelled"
    try:
        buf.load(path)
    except Exception as exc:
        return current_language, f"Error opening file: {exc}"
    if buf.load_error:
        # Binary/non-text or unreadable file: the buffer is inert; surface
        # the reason as the status instead of opening an empty document.
        err = buf.load_error
        buf.load_error = None
        return current_language, err
    if buf.image_format is not None:
        # Image file: hand it to the default browser (name it in the status
        # line) instead of auto-taking-over the screen with the terminal
        # viewer.  The inert placeholder buffer stays; Ctrl-\ still opens
        # the in-terminal viewer on demand.
        language = schema.detect_language(buf.filename or "")
        ok, info = runner.open_in_browser(path)
        if ok:
            return language, f"Opened {path} in the default browser"
        return language, f"Could not open image in browser: {info}"
    language = schema.detect_language(buf.filename or "")
    if explorer is not None:
        abs_path = os.path.abspath(path)
        parent = os.path.dirname(abs_path)
        try:
            inside = os.path.commonpath([explorer.root_dir, abs_path]) == explorer.root_dir
        except ValueError:  # e.g. unrelated Windows drives
            inside = False
        if inside:
            # The file lives inside the current tree (typical when a
            # project root was given): keep that root and just reveal
            # the file — expand its ancestors, refresh, highlight it.
            node = parent
            while node != explorer.root_dir and len(node) > len(explorer.root_dir):
                explorer.expanded_dirs.add(node)
                node = os.path.dirname(node)
            explorer.refresh()
            explorer._select_path(abs_path)
        else:
            # Outside the current tree: re-root at the file's folder.
            explorer.set_root(parent)
        explorer.current_path = abs_path
    recent.add_recent(path)
    return language, f"Opened {path}"


def format_status_bar(
    filename,
    modified,
    label,
    cursor_y,
    cursor_x,
    line_count,
    selecting=False,
    large_file_mode=False,
    match_pos=None,
    meter_label="",
    extension_status="",
    transient_status="",
    icon="",
    width=0,
    git_branch=None,
    git_counts=None,
) -> str:
    """Build the status bar text.

    Pure function (no curses access) so it can be unit tested.  When
    *width* > 0 the bar is split into a left segment (file info and
    flags) and a right segment (position and scroll %), filled to the
    full terminal width so it always spans the bottom row.
    """
    name = f"{filename or '[No Name]'}{'*' if modified else ''}"
    sel_flag = " [SELECT]" if selecting else ""
    large_flag = " [LARGE-FILE: undo off]" if large_file_mode else ""
    match_flag = f" [MATCH {match_pos[0]+1}:{match_pos[1]+1}]" if match_pos else ""
    if line_count > 0:
        pct = max(0, min(100, round((cursor_y + 1) / line_count * 100)))
        pct_text = f"  {pct}%"
    else:
        pct_text = ""

    left = f"{name}  [{icon + ' ' if icon else ''}{label}]{sel_flag}{large_flag}{match_flag}"
    # Add git branch and status counts if available
    if git_branch:
        left += f"  {git_branch}"
    git_status = git.format_status_counts(git_counts or {})
    if git_status:
        left += f"  {git_status}"
    right = f"Ln {cursor_y + 1}, Col {cursor_x + 1}{pct_text}"

    extras = []
    if transient_status:
        extras.append(transient_status)
    if meter_label:
        extras.append(meter_label)
    if extension_status:
        extras.append(extension_status)
    extra_part = "  ".join(extras)

    if width <= 0:
        parts = [f"{left}  {right}"]
        if extra_part:
            parts.append(extra_part)
        return "   ".join(parts)

    sep = " \u2502 "  # thin vertical separator between left and right
    gap = max(1, width - len(left) - len(sep) - len(right))
    bar = f"{left}{' ' * gap}{sep}{right}"
    if extra_part:
        bar = f"{extra_part}   {bar}"
    return bar[:width - 1]


def _draw_explorer(stdscr, explorer: FileExplorer, height: int, width: int,
                   icons_on: bool = False) -> None:
    """Draw the file explorer panel on the left side."""
    # Draw vertical separator
    for row in range(height):
        try:
            stdscr.addstr(row, width - 1, "│", curses.A_DIM)
        except curses.error:
            pass

    # Search mode: 3-row area at the top (label, input, separator)
    if explorer.searching:
        # Row 0: label
        label = " Search "
        try:
            stdscr.addstr(0, 0, label.ljust(width - 2)[:width - 2],
                          curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass
        # Row 1: input field with cursor
        query_text = f" /{explorer.search_query}"
        cursor = "_"
        field = (query_text + cursor)[:width - 2]
        try:
            stdscr.addstr(1, 0, field.ljust(width - 2)[:width - 2],
                          curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass
        # Row 2: separator line
        sep = " " + "~" * (width - 3)
        try:
            stdscr.addstr(2, 0, sep[:width - 2], curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass
        # Offset items below the 3-row search area
        draw_height = height - 3
        item_offset = 3
    else:
        draw_height = height
        item_offset = 0

    # Draw explorer items
    visible_items = explorer.search_results if explorer.searching else explorer.items[:]
    start_idx = max(0, explorer.selected_idx - draw_height // 2)
    end_idx = min(len(visible_items), start_idx + draw_height)

    for i, row in enumerate(range(start_idx, end_idx)):
        if row >= len(visible_items):
            break
        depth, name, path, is_dir = visible_items[row]
        indent = "  " * depth
        prefix = "" if is_dir or path == ".." else (
            icons.icon_for_file(path, icons_on) + " " if icons_on else "")
        display = f"{indent}{prefix}{name}"[:width - 2]

        attr = curses.A_REVERSE if row == explorer.selected_idx else 0
        if is_dir and row != explorer.selected_idx:
            attr |= curses.A_BOLD
        elif not is_dir and path == explorer.current_path:
            # Highlight the file that is currently open in the editor.
            attr |= curses.A_BOLD | curses.A_UNDERLINE

        try:
            stdscr.addstr(item_offset + i, 0, _safe_render(display.ljust(width - 2)[:width - 2]), attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass


def _draw_gutter(stdscr, row: int, line_idx: int, line_count: int, gutter_width: int, x_offset: int = 0) -> None:
    """Draw a stable, 1-indexed line-number gutter.

    The gutter is intentionally outside the horizontally scrolling text area,
    so line numbers never disappear or restart when the text scrolls.
    """
    digits = line_number_width(line_count)
    if line_idx < line_count:
        label = str(line_idx + 1).rjust(digits)
    else:
        label = " " * digits
    label = f"{label} "  # one separator column
    try:
        stdscr.addstr(row, x_offset, label[:gutter_width], curses.A_DIM)
    except curses.error:
        pass


def _highlight_selection(stdscr, row, line_idx, line, buf, scroll_x, width, x_offset=0) -> None:
    """Re-draw the selected portion of this row in reverse video, if any."""
    if not buf.has_selection():
        return
    ay, ax = buf.selection_anchor
    by, bx = buf.cursor_y, buf.cursor_x
    sy, sx, ey, ex = (ay, ax, by, bx) if (ay, ax) <= (by, bx) else (by, bx, ay, ax)
    if line_idx < sy or line_idx > ey:
        return
    start = sx if line_idx == sy else 0
    end = ex if line_idx == ey else len(line)
    if start >= end:
        return
    _addstr_clip(stdscr, row, start, line[start:end], scroll_x, width, curses.A_REVERSE, x_offset)


def _highlight_find_match(stdscr, row, line_idx, width, scroll_x, x_offset) -> None:
    """Highlight the current find-match on this row, if any."""
    if not _search["query"] or not _search["matches"]:
        return
    m_line, m_start, m_end = _search["matches"][_search["idx"]]
    if m_line != line_idx:
        return
    col = m_start - scroll_x
    end_col = m_end - scroll_x
    if end_col <= 0 or col >= width:
        return
    vis_start = max(0, col)
    vis_end = min(end_col, width)
    if vis_start < vis_end:
        try:
            stdscr.addstr(row, x_offset + vis_start,
                          " " * (vis_end - vis_start),
                          curses.A_REVERSE | curses.A_BOLD)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass


def _draw_line(stdscr, row: int, line: str, scroll_x: int, width: int, language: str, x_offset=0) -> None:
    """Draw one line, colorizing tokens returned by the language tokenizer."""
    spans = schema.tokenize(line, language)
    if not spans:
        try:
            stdscr.addstr(row, x_offset, _safe_render(line[scroll_x : scroll_x + width]))
        except (curses.error, ValueError, UnicodeEncodeError):
            pass
        return

    pos = 0
    col = 0
    for start, end, token_type in spans:
        if start > pos:
            col = _addstr_clip(stdscr, row, col, line[pos:start], scroll_x, width, 0, x_offset)
        pair = _COLOR_PAIRS.get(token_type, 0)
        attr = curses.color_pair(pair) if pair else 0
        col = _addstr_clip(stdscr, row, col, line[start:end], scroll_x, width, attr, x_offset)
        pos = end
    if pos < len(line):
        _addstr_clip(stdscr, row, col, line[pos:], scroll_x, width, 0, x_offset)


def _addstr_clip(stdscr, row: int, col: int, text: str, scroll_x: int, width: int, attr: int, x_offset: int = 0) -> int:
    """Write `text` at logical column `col`, respecting horizontal scroll,
    and return the next logical column. Screen writes are clipped to width."""
    text = _safe_render(text)
    next_col = col + len(text)
    screen_start = col - scroll_x
    screen_end = next_col - scroll_x
    if screen_end <= 0 or screen_start >= width:
        return next_col  # entirely off-screen
    visible_start = max(0, -screen_start)
    visible_end = min(len(text), width - screen_start)
    if visible_end > visible_start:
        try:
            stdscr.addstr(row, x_offset + max(0, screen_start), text[visible_start:visible_end], attr)
        except (curses.error, ValueError, UnicodeEncodeError):
            pass
    return next_col
