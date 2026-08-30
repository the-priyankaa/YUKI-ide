import curses
import os
import unittest
from unittest import mock

from stdedit.tui import (
    _get_key,
    _autosave_step,
    _auto_save_on_edit,
    build_help_lines,
    is_help_toggle,
    line_number_width,
    format_status_bar,
    _lines_fingerprint,
    _insert_text,
    _ghost_wanted,
    _in_double_quoted,
    _draw_ghost,
    _draw_suggest_overlay,
    _fetch_ghost_text,
    _draw_settings_overlay,
    _draw_quick_open_overlay,
    _forget_image_pixels,
    RecentPicker,
    _draw_recent_overlay,
    _is_ctrl_1,
    _leave_to_dashboard,
    _overlay_signature,
    _quick_open_cursor_col,
    _quick_open_geometry,
)
from stdedit.buffer import Buffer
from stdedit import suggest
from stdedit.quick_open import QuickOpen

import tempfile as _tempfile
import pathlib as _pathlib

_TMP_RECENT_DIR = _pathlib.Path(_tempfile.mkdtemp(prefix="stdedit-test-tui-"))
_RECENT_ORIG_DIR = None
_RECENT_ORIG_FILE = None


def setUpModule():
    """Sandbox the recent-files store so test opens never touch the real one."""
    from stdedit import recent
    global _RECENT_ORIG_DIR, _RECENT_ORIG_FILE
    _RECENT_ORIG_DIR = recent.CONFIG_DIR
    _RECENT_ORIG_FILE = recent.RECENT_FILE
    recent.CONFIG_DIR = _TMP_RECENT_DIR
    recent.RECENT_FILE = _TMP_RECENT_DIR / "recent.json"
    recent._recent = []


def tearDownModule():
    from stdedit import recent
    recent.CONFIG_DIR = _RECENT_ORIG_DIR
    recent.RECENT_FILE = _RECENT_ORIG_FILE
    recent._recent = []


class TestLineNumbers(unittest.TestCase):
    def test_line_number_width_is_stable_for_small_files(self):
        self.assertEqual(line_number_width(1), 2)
        self.assertEqual(line_number_width(9), 2)
        self.assertEqual(line_number_width(10), 2)

    def test_line_number_width_grows_with_document(self):
        self.assertEqual(line_number_width(99), 2)
        self.assertEqual(line_number_width(100), 3)
        self.assertEqual(line_number_width(1000), 4)


class TestStatusBar(unittest.TestCase):
    def test_shows_filename_and_type(self):
        line = format_status_bar("main.py", False, "Python", 0, 0, 10)
        self.assertIn("main.py", line)
        self.assertIn("[Python]", line)
        self.assertIn("Ln 1, Col 1", line)

    def test_dirty_marker_after_filename(self):
        line = format_status_bar("main.py", True, "Python", 0, 0, 10)
        self.assertIn("main.py*", line)

    def test_no_name_when_no_file(self):
        line = format_status_bar(None, False, "Text", 0, 0, 1)
        self.assertIn("[No Name]  [Text]", line)

    def test_position_percent(self):
        # Cursor on line 5 of 10 -> 50%.
        line = format_status_bar("f.py", False, "Python", 4, 0, 10)
        self.assertIn("50%", line)

    def test_single_line_file_is_100_percent(self):
        line = format_status_bar("f.py", False, "Python", 0, 0, 1)
        self.assertIn("100%", line)

    def test_optional_segments_omitted(self):
        line = format_status_bar("f.py", False, "Python", 0, 0, 5)
        self.assertNotIn("[SELECT]", line)
        self.assertNotIn("[MATCH", line)
        self.assertNotIn("[LARGE-FILE", line)

    def test_flags_included_when_active(self):
        line = format_status_bar(
            "big.log", False, "Text", 3, 2, 100,
            selecting=True, large_file_mode=True, match_pos=(7, 9),
        )
        self.assertIn("[SELECT]", line)
        self.assertIn("[LARGE-FILE: undo off]", line)
        self.assertIn("[MATCH 8:10]", line)


class TestTreeRoot(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_project_dir_wins_over_everything(self):
        from stdedit.tui import resolve_tree_root

        self.assertEqual(
            resolve_tree_root("some/missing/file.py", self.tmp),
            os.path.abspath(self.tmp),
        )

    def test_opened_file_parent_is_default(self):
        from stdedit.tui import resolve_tree_root

        target = os.path.join(self.tmp, "f.py")
        with open(target, "w") as f:
            f.write("x\n")
        self.assertEqual(resolve_tree_root(target, None), self.tmp)

    def test_cwd_fallback_without_file_or_project(self):
        from stdedit.tui import resolve_tree_root

        self.assertEqual(resolve_tree_root(None, None), ".")
        # A filename that does not exist on disk behaves like no file.
        self.assertEqual(resolve_tree_root("/no/such/f.py", None), ".")


class TestGetKey(unittest.TestCase):
    """Physical Enter must be readable as "\\n" (curses.KEY_ENTER bug)."""

    class _S:
        def __init__(self, keys):
            self._keys = iter(keys)

        def get_wch(self):
            k = next(self._keys)
            if isinstance(k, Exception):
                raise k
            return k

    def test_keypad_enter_is_normalized_to_newline(self):
        self.assertEqual(_get_key(self._S([curses.KEY_ENTER])), "\n")

    def test_regular_keys_pass_through_untouched(self):
        for raw in ("\r", "\n", "a", "?", curses.KEY_UP, curses.KEY_F1):
            self.assertEqual(_get_key(self._S([raw])), raw)

    def test_curses_error_reports_none(self):
        self.assertIsNone(_get_key(self._S([curses.error("no input")])))


class TestHelpContent(unittest.TestCase):
    def test_documents_every_binding(self):
        text = "\n".join(build_help_lines(200))
        for token in (
            "Ctrl-Space", "Ctrl-C", "Ctrl-X", "Ctrl-V", "Ctrl-Z",
            "Ctrl-Y", "Ctrl-S", "Ctrl-O", "Ctrl-Q", "Ctrl-E", "Ctrl-H",
            "F1", "Enter", "Tab", "Backspace", "Home", "End",
            "h ", "n ", "N ", "O ", "R ",
            "( { [", ") } ]", "auto-close quotes",
            "bracketed paste", "Esc cancels", "prompt Backspace",
        ):
            self.assertIn(token, text, token)

    def test_covers_all_sections_and_dismissal(self):
        text = "\n".join(build_help_lines(200))
        for section in ("EDITING", "SELECTION & CLIPBOARD",
                        "HISTORY & FILES", "FILE TREE",
                        "GIT STATUS", "SOURCE CONTROL",
                        "DIFF VIEWER", "SETTINGS", "MOUSE",
                        "TERMINAL & PROMPTS", "HELP"):
            self.assertIn(section, text)
        self.assertIn("q / Esc / Enter", text)

    def test_lines_fit_narrow_widths(self):
        for width in (40, 60, 80):
            for line in build_help_lines(width):
                self.assertLessEqual(len(line), width)


class TestHelpToggle(unittest.TestCase):
    def test_raw_ctrl_h_and_f1_work_anywhere(self):
        for tree_active in (False, True):
            self.assertTrue(is_help_toggle("\x08", tree_active))
            self.assertTrue(is_help_toggle(curses.KEY_F1, tree_active))

    def test_backspace_constant_never_toggles(self):
        # Backspace should never open the help overlay.
        self.assertFalse(is_help_toggle(curses.KEY_BACKSPACE, True))
        self.assertFalse(is_help_toggle(curses.KEY_BACKSPACE, False))

    def test_raw_ctrl_h_byte_is_the_literal_backspace_char(self):
        # "\\b" == "\\x08": one byte, so raw Ctrl-H toggles everywhere.
        self.assertEqual("\b", "\x08")
        self.assertTrue(is_help_toggle("\x08", False))

    def test_normal_keys_never_toggle(self):
        for key in ("a", "\n", "\r", "\x1b", curses.KEY_DOWN,
                    curses.KEY_RESIZE):
            self.assertFalse(is_help_toggle(key, True))
            self.assertFalse(is_help_toggle(key, False))


class TestPrompts(unittest.TestCase):
    def test_unsaved_prompt_choices(self):
        from stdedit.tui import _unsaved_changes_prompt

        self.assertEqual(_unsaved_changes_prompt(iter(["s"]).__next__), "save")
        self.assertEqual(_unsaved_changes_prompt(iter(["D"]).__next__), "discard")
        self.assertEqual(_unsaved_changes_prompt(iter(["c"]).__next__), "cancel")
        self.assertEqual(_unsaved_changes_prompt(iter(["\x1b"]).__next__), "cancel")

    def test_unsaved_prompt_reprompts_on_invalid_keys(self):
        from stdedit.tui import _unsaved_changes_prompt

        keys = iter(["x", "\n", "d"])
        self.assertEqual(_unsaved_changes_prompt(keys.__next__), "discard")

    def test_unsaved_prompt_renders_message_once(self):
        from stdedit.tui import _unsaved_changes_prompt

        seen = []
        _unsaved_changes_prompt(iter(["s"]).__next__, seen.append)
        self.assertEqual(seen, ["Unsaved changes — (s)ave, (d)iscard, (c)ancel?"])

    def test_yes_no_prompt_matrix(self):
        from stdedit.tui import _yes_no_prompt

        for key, expected in (("y", True), ("Y", True),
                              ("\n", True), ("\r", True),
                              ("n", False), ("N", False),
                              ("\x1b", False)):
            self.assertEqual(
                _yes_no_prompt(iter([key]).__next__, lambda t: None, "?"),
                expected, repr(key))

    def test_yes_no_prompt_reprompts_on_other_keys(self):
        from stdedit.tui import _yes_no_prompt

        keys = iter(["x", "1", " ", "y"])
        self.assertTrue(_yes_no_prompt(keys.__next__, lambda t: None, "?"))

    def test_yes_no_prompt_renders_message_once(self):
        from stdedit.tui import _yes_no_prompt

        seen = []
        _yes_no_prompt(iter(["y"]).__next__, seen.append, "create?")
        self.assertEqual(seen, ["create?"])

    def test_prompt_line_types_backspaces_and_submits(self):
        from stdedit.tui import _prompt_line

        keys = iter(list("src/st") + ["\x7f", "p", "\r"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "src/sp")

    def test_prompt_line_esc_cancels(self):
        from stdedit.tui import _prompt_line

        self.assertIsNone(_prompt_line(iter(["a", "\x1b"]).__next__, lambda t: None))

    def test_prompt_line_key_backspace_constant_deletes(self):
        from stdedit.tui import _prompt_line

        # Real terminals deliver Backspace as curses.KEY_BACKSPACE (263),
        # not "\b"/"\x7f" -- it must delete like the byte forms.
        keys = iter(["a", "b", curses.KEY_BACKSPACE, "c", "\n"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "ac")

    def test_prompt_line_backspace_on_empty_text_is_noop(self):
        from stdedit.tui import _prompt_line

        keys = iter([curses.KEY_BACKSPACE, "x", "\n"])
        self.assertEqual(_prompt_line(keys.__next__, lambda t: None), "x")

    def test_prompt_line_empty_submit_is_cancel(self):
        from stdedit.tui import _prompt_line

        self.assertIsNone(_prompt_line(iter(["\n"]).__next__, lambda t: None))


class TestTreeSwallow(unittest.TestCase):
    """Printable keys must be swallowed while the tree has focus (bug 2)."""

    def test_printable_characters_are_swallowed(self):
        from stdedit.tui import swallowed_by_tree

        for ch in ("x", "A", "1", " ", "!", "é"):
            self.assertTrue(swallowed_by_tree(ch), repr(ch))

    def test_controls_and_special_keys_pass_through(self):
        from stdedit.tui import swallowed_by_tree

        for key in ("\n", "\r", "\t", "\x13", "\x1b",
                    curses.KEY_DOWN, curses.KEY_BACKSPACE, curses.KEY_F1,
                    None):
            self.assertFalse(swallowed_by_tree(key), repr(key))


class TestHelpScroll(unittest.TestCase):
    def test_clamp_scroll_bounds(self):
        from stdedit.tui import clamp_scroll

        # total 50 lines, viewport 20 -> max offset 30
        self.assertEqual(clamp_scroll(0, 1, 50, 20), 1)
        self.assertEqual(clamp_scroll(0, -1, 50, 20), 0)
        self.assertEqual(clamp_scroll(29, 5, 50, 20), 30)
        self.assertEqual(clamp_scroll(30, 5, 50, 20), 30)   # bottom clamp
        self.assertEqual(clamp_scroll(0, -99, 50, 20), 0)   # top clamp

    def test_clamp_scroll_fits_without_scrolling(self):
        from stdedit.tui import clamp_scroll

        # Content shorter than the viewport never scrolls.
        self.assertEqual(clamp_scroll(0, 10, 12, 20), 0)

    def test_clamp_scroll_degenerate_viewports(self):
        from stdedit.tui import clamp_scroll

        self.assertEqual(clamp_scroll(5, 1, 50, 0), 0)
        self.assertEqual(clamp_scroll(5, 1, 0, 20), 0)


class TestIcons(unittest.TestCase):
    def test_language_icons_cover_supported_languages(self):
        from stdedit.icons import LANG_ICONS, icon_for_language

        for lang in ("python", "javascript", "typescript", "html", "css",
                     "c", "cpp", "java", "rust", "go", "json", "yaml",
                     "markdown", "shell", "sql", "xml", "plaintext"):
            self.assertTrue(LANG_ICONS[lang], lang)
            self.assertEqual(icon_for_language(lang.upper(), True),
                             LANG_ICONS[lang])

    def test_disabled_icons_return_empty(self):
        from stdedit.icons import enabled_from_env, icon_for_file, \
            icon_for_language

        self.assertEqual(icon_for_file("x.py", False), "")
        self.assertEqual(icon_for_language("python", False), "")
        self.assertFalse(enabled_from_env({"STDEDIT_ICONS": "0"}))
        self.assertTrue(enabled_from_env({}))
        self.assertTrue(enabled_from_env({"STDEDIT_ICONS": "1"}))

    def test_extension_and_default_icons(self):
        from stdedit.icons import DEFAULT_ICON, icon_for_file

        self.assertEqual(icon_for_file("Cargo.lock", True), "\uF023")
        self.assertEqual(icon_for_file("pic.PNG", True), "\uF1C5")
        self.assertEqual(icon_for_file("setup.cfg", True), "\uF013")
        self.assertEqual(icon_for_file("unknown.xyz", True), DEFAULT_ICON)

    def test_status_bar_renders_icon_inside_brackets(self):
        from stdedit.tui import format_status_bar

        line = format_status_bar("main.py", False, "Python", 0, 0, 10,
                                 icon="\uE73C")
        self.assertIn("[\uE73C Python]", line)
        plain = format_status_bar("main.py", False, "Python", 0, 0, 10)
        self.assertIn("[Python]", plain)


class TestSafeOpen(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.target = os.path.join(self._tmp.name, "target.py")
        with open(self.target, "w") as f:
            f.write("x = 1\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_load_opens_and_syncs_explorer(self):
        from stdedit.buffer import Buffer
        from stdedit.explorer import FileExplorer
        from stdedit.tui import open_file_path

        buf = Buffer()
        explorer = FileExplorer(".")
        language, status = open_file_path(None, buf, explorer, self.target)
        self.assertEqual(language, "python")
        self.assertTrue(status.startswith("Opened "))
        self.assertEqual(buf.lines, ["x = 1", ""])
        self.assertEqual(explorer.current_path, os.path.abspath(self.target))
        self.assertEqual(explorer.root_dir, os.path.abspath(self._tmp.name))

    def _write(self, relpath, content):
        path = os.path.join(self._tmp.name, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(path, mode) as f:
            f.write(content)
        return path

    def test_open_inside_project_keeps_root_and_selects_file(self):
        from stdedit.buffer import Buffer
        from stdedit.explorer import FileExplorer
        from stdedit.tui import open_file_path

        marker = self._write("marker.txt", "m\n")
        nested = self._write(os.path.join("sub", "deep.txt"), "deep\n")

        explorer = FileExplorer(self._tmp.name)
        buf = Buffer()
        language, status = open_file_path(None, buf, explorer, nested)

        self.assertTrue(status.startswith("Opened "))
        # The project root stays pinned -- no jump into sub/.
        self.assertEqual(explorer.root_dir, os.path.abspath(self._tmp.name))
        # Root-level content is still listed; sub/ got expanded.
        listed = [item[2] for item in explorer.items]
        self.assertIn(os.path.abspath(marker), listed)
        self.assertIn(os.path.abspath(nested), listed)
        self.assertIn(os.path.abspath(os.path.dirname(nested)),
                      explorer.expanded_dirs)
        # And the opened file is highlighted in the tree.
        self.assertEqual(explorer.current_path, os.path.abspath(nested))
        selected = explorer.get_selected()
        self.assertIsNotNone(selected)
        self.assertEqual(selected[2], os.path.abspath(nested))

    def test_open_outside_project_reroots_at_parent(self):
        from stdedit.buffer import Buffer
        from stdedit.explorer import FileExplorer
        from stdedit.tui import open_file_path

        proj = os.path.join(self._tmp.name, "proj")
        os.mkdir(proj)
        stray = self._write("stray.txt", "outside\n")

        explorer = FileExplorer(proj)
        language, status = open_file_path(None, Buffer(), explorer, stray)

        self.assertTrue(status.startswith("Opened "))
        self.assertEqual(explorer.root_dir, os.path.abspath(self._tmp.name))
        self.assertEqual(explorer.current_path, os.path.abspath(stray))

    def test_modified_buffer_discard_choice_loads_new_file(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        class FakeStdscr:
            def __init__(self, keys):
                self._keys = iter(keys)

            def get_wch(self):
                return next(self._keys)

        buf = Buffer()
        buf.insert_char("z")  # makes it modified
        self.assertTrue(buf.modified)
        _, status = open_file_path(FakeStdscr(["d"]), buf, None, self.target)
        self.assertTrue(status.startswith("Opened "))
        self.assertEqual(buf.lines, ["x = 1", ""])

    def test_modified_buffer_cancel_keeps_content(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        class FakeStdscr:
            def get_wch(self):
                return "\x1b"

        buf = Buffer()
        buf.insert_char("z")
        _, status = open_file_path(FakeStdscr(), buf, None, self.target)
        self.assertEqual(status, "Open cancelled")
        self.assertEqual(buf.lines, ["z"])

    def test_save_without_filename_cancels_open(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        class FakeStdscr:
            def get_wch(self):
                return "s"

        buf = Buffer()  # no filename -> save raises ValueError internally
        buf.insert_char("z")
        _, status = open_file_path(FakeStdscr(), buf, None, self.target)
        self.assertIn("cannot save", status)
        self.assertEqual(buf.lines, ["z"])

    def test_missing_file_reports_error(self):
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        buf = Buffer()
        _, status = open_file_path(None, buf, None, "/nonexistent/nope.py")
        self.assertIn("Error opening file", status)

    def test_image_open_hands_image_to_default_browser(self):
        import struct
        import zlib
        from unittest import mock

        from stdedit import runner
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        def chunk(ctype, data):
            c = struct.pack(">I", len(data)) + ctype + data
            return c + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
               + chunk(b"IEND", b""))
        path = self._write("pic.png", png)

        buf = Buffer()
        with mock.patch.object(runner, "open_in_browser",
                               return_value=(True, "Opening: pic.png (xdg-open)")) as ob:
            language, status = open_file_path(None, buf, None, path)

        self.assertEqual(ob.call_args.args[0], path)
        self.assertTrue(status.startswith("Opened "))
        self.assertIn("default browser", status)
        self.assertEqual(buf.image_format, "png")
        self.assertEqual(buf.image_path, path)

    def test_image_open_failure_surfaces_reason(self):
        import struct
        import zlib
        from unittest import mock

        from stdedit import runner
        from stdedit.buffer import Buffer
        from stdedit.tui import open_file_path

        def chunk(ctype, data):
            c = struct.pack(">I", len(data)) + ctype + data
            return c + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
               + chunk(b"IEND", b""))
        path = self._write("pic.png", png)

        buf = Buffer()
        with mock.patch.object(runner, "open_in_browser",
                               return_value=(False, "no browser opener found")):
            _, status = open_file_path(None, buf, None, path)
        self.assertIn("Could not open image in browser", status)
        self.assertIn("no browser opener found", status)
        self.assertEqual(buf.image_format, "png")


class _FakeStdscr:
    def __init__(self, text):
        self._items = [ord(ch) for ch in text]

    def getch(self):
        return self._items.pop(0) if self._items else -1

    def nodelay(self, flag):
        pass

    def ungetch(self, ch):
        self._items.insert(0, ch)


class TestBracketedPaste(unittest.TestCase):
    def test_reads_payload_without_leaking_marker_characters(self):
        from stdedit.tui import _read_bracketed_paste

        # ESC and '[' were already consumed by _main_loop.
        stdscr = _FakeStdscr("200~def greet():\n    return 'hi'\x1b[201~")
        self.assertEqual(
            _read_bracketed_paste(stdscr),
            "def greet():\n    return 'hi'",
        )
        self.assertEqual(stdscr._items, [])


class TestSearchIntegration(unittest.TestCase):
    def test_search_mode_enter_exit(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        self.assertTrue(e.searching)
        e.exit_search()
        self.assertFalse(e.searching)

    def test_search_results_replace_items_in_draw(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        e.search("__init__")
        self.assertTrue(len(e.search_results) > 0)
        # All results should be flat (depth=0)
        for item in e.search_results:
            self.assertEqual(item[0], 0)

    def test_search_query_updates(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        e.search("test")
        self.assertEqual(e.search_query, "test")
        e.search("test_")
        self.assertEqual(e.search_query, "test_")

    def test_exit_search_clears_state(self):
        from stdedit.explorer import FileExplorer
        e = FileExplorer(".")
        e.enter_search()
        e.search("something")
        e.exit_search()
        self.assertEqual(e.search_query, "")
        self.assertEqual(e.search_results, [])


class TestMouseMultiClick(unittest.TestCase):
    def test_scroll_wheel_up(self):
        import curses
        from stdedit.buffer import Buffer
        from stdedit.tui import _mouse_dragging, _last_click_time, _click_count
        b = Buffer()
        b.lines = [f"line{i}" for i in range(50)]
        b.move_to(0, 25)
        b.update_scroll(20, 80)
        b.move_cursor(dy=-3)
        b.update_scroll(20, 80)
        self.assertLess(b.cursor_y, 25)

    def test_scroll_wheel_down(self):
        from stdedit.buffer import Buffer
        b = Buffer()
        b.lines = [f"line{i}" for i in range(50)]
        b.move_to(0, 0)
        b.update_scroll(20, 80)
        b.move_cursor(dy=3)
        b.update_scroll(20, 80)
        self.assertGreater(b.cursor_y, 0)

    def test_select_word_and_line(self):
        from stdedit.buffer import Buffer
        b = Buffer()
        b.lines = ["hello world"]
        b.select_word_at(0, 2)
        self.assertEqual(b.selected_text(), "hello")
        b.select_line_at(0)
        self.assertEqual(b.selected_text(), "hello world")


class TestFontFamily(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from stdedit import settings
        settings._settings = dict(settings._DEFAULTS)
        tmp = Path(tempfile.mkdtemp()) / "settings.json"
        self._mgr = mock.patch.object(settings, "CONFIG_FILE", tmp)
        self._mgr.start()

    def tearDown(self):
        self._mgr.stop()

    def test_settings_panel_includes_font_keys(self):
        from stdedit import settings
        keys = [k for k, _ in settings.LABELS if k is not None]
        for fk in settings._font_keys:
            self.assertIn(fk, keys)

    def test_apply_font_family_sends_osc(self):
        from stdedit import tui
        import io
        import sys
        from unittest.mock import patch
        from stdedit import settings
        fake = io.StringIO()
        with patch.object(sys, "stdout", fake):
            tui._apply_font_family()
        output = fake.getvalue()
        self.assertIn("\033]50;", output)
        self.assertIn("\007", output)

    def test_apply_font_family_with_no_font(self):
        from stdedit import tui
        from stdedit import settings
        for fk in settings._font_keys:
            settings.set(fk, False)
        import io
        import sys
        from unittest.mock import patch
        fake = io.StringIO()
        with patch.object(sys, "stdout", fake):
            tui._apply_font_family()
        self.assertEqual(fake.getvalue(), "")


class TestSettingsDropdown(unittest.TestCase):
    def setUp(self):
        from stdedit import settings
        self.settings = settings
        settings._settings = dict(settings._DEFAULTS)

    def test_all_collapsed_nav_is_only_headers(self):
        from stdedit.tui import _settings_nav_indices
        from stdedit import settings
        headers = [i for i, (k, _) in enumerate(settings.LABELS)
                   if k is None and settings.LABELS[i][1]]
        self.assertEqual(_settings_nav_indices({}), headers)
        self.assertEqual(len(headers), 4)  # AUTO-SAVE, THEME, FONT FAMILY, SUGGESTIONS

    def test_expanded_section_shows_items(self):
        from stdedit.tui import _settings_nav_indices
        from stdedit import settings
        theme_keys = set(settings._theme_keys)
        nav = set(_settings_nav_indices({"THEME": True}))
        self.assertGreater(len(nav), 10)  # headers + all 15 themes
        for i, (k, _) in enumerate(settings.LABELS):
            if k in theme_keys:
                self.assertIn(i, nav, f"{k} should be listed")
            elif k is not None:
                self.assertNotIn(i, nav, f"{k} should be hidden")

    def test_headers_always_navigable(self):
        from stdedit.tui import _settings_nav_indices
        nav = _settings_nav_indices({"AUTO-SAVE": True, "FONT FAMILY": True})
        headers = {"AUTO-SAVE", "THEME", "FONT FAMILY"}
        for i in nav:
            if self.settings.LABELS[i][0] is None:
                headers.discard(self.settings.LABELS[i][1])
        self.assertEqual(headers, set())

    def test_display_rows_all_collapsed(self):
        from stdedit.tui import _settings_display_rows
        rows = _settings_display_rows({})
        kinds = [r[0] for r in rows]
        self.assertEqual(kinds, ["header", "header", "header", "header"])
        for r in rows:
            self.assertEqual(r[0], "header")

    def test_display_rows_expanded_adds_items_and_separator(self):
        from stdedit.tui import _settings_display_rows
        rows = _settings_display_rows({"THEME": True})
        kinds = [r[0] for r in rows]
        self.assertEqual(kinds.count("header"), 4)
        self.assertEqual(kinds.count("item"), len(self.settings._theme_keys))
        self.assertEqual(kinds.count("separator"), 1)

    def test_display_layout_selection_centered_expanded(self):
        from stdedit.tui import _settings_display_rows
        from stdedit.tui import _settings_display_layout
        rows = _settings_display_rows({"THEME": True})
        item_idx = next(r[4] for r in rows if r[0] == "item")
        _, start = _settings_display_layout({"THEME": True}, item_idx, 10)
        # The selected item is visible within the viewport.
        sel_pos = next(i for i, r in enumerate(rows) if r[0] == "item" and r[4] == item_idx)
        self.assertLessEqual(start, sel_pos)
        self.assertLess(sel_pos - start, 10)


class TestSettingsAccordion(unittest.TestCase):
    def setUp(self):
        from stdedit import settings
        self.settings = settings
        settings._settings = dict(settings._DEFAULTS)

    def test_close_others_keeps_one(self):
        from stdedit.tui import _settings_close_others
        exp = {"AUTO-SAVE": True, "THEME": True, "FONT FAMILY": True}
        _settings_close_others(exp, "THEME")
        self.assertEqual(exp, {"AUTO-SAVE": False, "THEME": True,
                                 "FONT FAMILY": False, "SUGGESTIONS": False})

    def test_close_others_none_clears_all(self):
        from stdedit.tui import _settings_close_others
        exp = {"AUTO-SAVE": True, "THEME": True, "FONT FAMILY": True}
        _settings_close_others(exp, None)
        self.assertFalse(any(exp.values()))

    def test_navigation_to_header_closes_previous(self):
        """
        With THEME expanded, navigating Down to the FONT FAMILY header must
        collapse THEME (single-open accordion).
        """
        from stdedit.tui import _settings_nav_indices, _settings_close_others
        from stdedit import settings
        exp = {"THEME": True}
        settings_idx = _settings_nav_indices(exp)[0]  # AUTO-SAVE header
        for _ in range(30):
            nav = _settings_nav_indices(exp)
            cur = nav.index(settings_idx) if settings_idx in nav else 0
            settings_idx = nav[(cur + 1) % len(nav)]
            if settings.LABELS[settings_idx][0] is None:
                _settings_close_others(exp, settings.LABELS[settings_idx][1])
                if settings.LABELS[settings_idx][1] == "FONT FAMILY":
                    break
        self.assertEqual(settings.LABELS[settings_idx][1], "FONT FAMILY")
        self.assertFalse(exp["THEME"])

    def test_open_one_after_heading_to_another(self):
        from stdedit.tui import _settings_close_others
        exp = {}
        _settings_close_others(exp, "THEME")
        exp["THEME"] = True
        _settings_close_others(exp, "FONT FAMILY")
        exp["FONT FAMILY"] = True
        self.assertEqual(exp["THEME"], False)
        self.assertEqual(exp["FONT FAMILY"], True)

    def test_suggestions_render_as_mutually_exclusive_radios(self):
        """Expanded SUGGESTIONS shows (x)/ ( ) radio rows, Off on by default."""
        from stdedit import settings
        settings._settings = dict(settings._DEFAULTS)

        class FakeScr:
            def __init__(self):
                self.lines = []

            def getmaxyx(self):
                return (24, 80)

            def addstr(self, row, col, text, attr):
                self.lines.append(text)

        s = FakeScr()
        _draw_settings_overlay(s, 0, 30, {"SUGGESTIONS": True})
        joined = "\n".join(s.lines)
        self.assertIn("(x) Suggestions: off", joined)
        self.assertIn("( ) Auto-suggest", joined)
        self.assertIn("( ) AI inline (Codeium)", joined)

    def test_suggestions_radio_marks_only_active(self):
        """With Auto-suggest selected, only its radio row is marked (x)."""
        from stdedit import settings
        saved = dict(settings._settings)
        try:
            settings._settings["suggestions_off"] = False
            settings._settings["suggestions_on"] = True
            settings._settings["codeium_on"] = False

            class FakeScr:
                def __init__(self):
                    self.lines = []

                def getmaxyx(self):
                    return (24, 80)

                def addstr(self, row, col, text, attr):
                    self.lines.append(text)

            s = FakeScr()
            _draw_settings_overlay(s, 0, 30, {"SUGGESTIONS": True})
            joined = "\n".join(s.lines)
            self.assertIn("( ) Suggestions: off", joined)
            self.assertIn("(x) Auto-suggest", joined)
            self.assertIn("( ) AI inline (Codeium)", joined)
        finally:
            settings._settings = saved


class TestQuitDialog(unittest.TestCase):
    def test_choices_unmodified(self):
        from stdedit.tui import _quit_dialog_choices
        self.assertEqual(_quit_dialog_choices(False, True),
                         [("Quit", "quit"), ("Cancel", "cancel")])
        self.assertEqual(_quit_dialog_choices(False, False),
                         [("Quit", "quit"), ("Cancel", "cancel")])

    def test_choices_modified_with_save(self):
        from stdedit.tui import _quit_dialog_choices
        self.assertEqual(_quit_dialog_choices(True, True),
                         [("Save & Quit", "save"), ("Discard & Quit", "discard"),
                          ("Cancel", "cancel")])

    def test_choices_modified_no_save(self):
        from stdedit.tui import _quit_dialog_choices
        self.assertEqual(_quit_dialog_choices(True, False),
                         [("Discard & Quit", "discard"), ("Cancel", "cancel")])

    def test_step_navigation_wraps(self):
        from stdedit.tui import _quit_dialog_choices, _quit_dialog_step
        choices = _quit_dialog_choices(True, True)
        sel, action = _quit_dialog_step(curses.KEY_LEFT, 0, choices)
        self.assertEqual(sel, len(choices) - 1)
        self.assertIsNone(action)
        sel, action = _quit_dialog_step(curses.KEY_RIGHT, len(choices) - 1, choices)
        self.assertEqual(sel, 0)
        self.assertIsNone(action)

    def test_step_enter_activates_focused(self):
        from stdedit.tui import _quit_dialog_choices, _quit_dialog_step
        choices = _quit_dialog_choices(True, True)
        self.assertEqual(_quit_dialog_step("\n", 1, choices)[1], "discard")
        self.assertEqual(_quit_dialog_step(" ", len(choices) - 1, choices)[1], "cancel")

    def test_step_shortcuts(self):
        from stdedit.tui import _quit_dialog_choices, _quit_dialog_step
        choices = _quit_dialog_choices(True, True)
        self.assertEqual(_quit_dialog_step("s", 0, choices)[1], "save")
        self.assertEqual(_quit_dialog_step("d", 0, choices)[1], "discard")
        self.assertEqual(_quit_dialog_step("q", 0, choices)[1], "discard")
        self.assertEqual(_quit_dialog_step("\x1b", 0, choices)[1], "cancel")

    def test_confirm_dialog_default_is_cancel(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["\n"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      True, True)
        self.assertEqual(result, "cancel")

    def test_confirm_dialog_quit_shortcut(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["q"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      False, True)
        self.assertEqual(result, "quit")

    def test_confirm_dialog_save_shortcut(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["s"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      True, True)
        self.assertEqual(result, "save")

    def test_confirm_dialog_esc_cancels(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter(["\x1b"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      True, False)
        self.assertEqual(result, "cancel")

    def test_confirm_dialog_select_then_enter(self):
        from stdedit.tui import _confirm_quit_dialog
        keys = iter([curses.KEY_LEFT, "\n"])
        result = _confirm_quit_dialog(lambda: next(keys), lambda c, s: None,
                                      False, True)
        self.assertEqual(result, "quit")

    def test_draw_quit_dialog_no_error(self):
        from stdedit.tui import _draw_quit_dialog, _quit_dialog_choices

        class FakeScr:
            def __init__(self):
                self.calls = []

            def getmaxyx(self):
                return (24, 80)

            def addstr(self, row, col, text, attr):
                self.calls.append((row, col, text))

        s = FakeScr()
        choices = _quit_dialog_choices(True, True)
        _draw_quit_dialog(s, "Quit stdedit?", ["Unsaved."], choices, 1)
        joined = "".join(t for _, _, t in s.calls)
        self.assertIn("[ Save & Quit ]", joined)
        self.assertIn("[ Discard & Quit ]", joined)
        self.assertIn("[ Cancel ]", joined)
        self.assertIn("\u250c", joined)
        self.assertIn("\u2518", joined)


class TestFingerprint(unittest.TestCase):
    def test_changes_on_edit(self):
        lines = ["foo", "bar baz"]
        self.assertNotEqual(_lines_fingerprint(lines),
                            _lines_fingerprint(lines + [""]))
        self.assertEqual(_lines_fingerprint(lines),
                         _lines_fingerprint(list(lines)))

    def test_scannable_window_only(self):
        base = [""] * 3000
        a = _lines_fingerprint(base)
        base[2999] = "changed"
        self.assertEqual(a, _lines_fingerprint(base))


class TestInsertText(unittest.TestCase):
    def make_buffer(self, text="", row=0, col=0):
        b = Buffer()
        if text:
            b.lines = text.split("\n")
        b.cursor_y = row
        b.cursor_x = col
        return b

    def test_single_line(self):
        b = self.make_buffer("abc", 0, 1)
        _insert_text(b, "XY")
        self.assertEqual(b.lines[0], "aXYbc")
        self.assertEqual((b.cursor_y, b.cursor_x), (0, 3))
        self.assertTrue(b.modified)

    def test_multi_line(self):
        b = self.make_buffer("abc\ndef", 0, 1)
        _insert_text(b, "X\nYZ")
        self.assertEqual(list(b.lines), ["aX", "YZbc", "def"])
        self.assertEqual((b.cursor_y, b.cursor_x), (1, 2))

    def test_multi_line_empty_tail_preserved(self):
        b = self.make_buffer("abc", 0, 3)
        _insert_text(b, "1\n2\n3")
        self.assertEqual(list(b.lines), ["abc1", "2", "3"])
        self.assertEqual((b.cursor_y, b.cursor_x), (2, 1))

    def test_empty_noop(self):
        b = self.make_buffer("abc", 0, 1)
        _insert_text(b, "")
        self.assertEqual(list(b.lines), ["abc"])
        self.assertFalse(b.modified)


class TestGhostWanted(unittest.TestCase):
    def make_buffer(self, text, col):
        b = Buffer()
        b.lines = [text]
        b.cursor_y = 0
        b.cursor_x = col
        return b

    def test_at_end_of_line(self):
        self.assertTrue(_ghost_wanted(self.make_buffer("print", 5)))

    def test_after_identifier_inside_line(self):
        self.assertFalse(_ghost_wanted(self.make_buffer("print(x)", 3)))

    def test_at_column_zero(self):
        self.assertTrue(_ghost_wanted(self.make_buffer("xy", 0)))

    def test_after_space(self):
        self.assertTrue(_ghost_wanted(self.make_buffer("a b", 2)))


class TestInDoubleQuoted(unittest.TestCase):
    def make_buffer(self, lines, col, row=0):
        b = Buffer()
        b.lines = [lines] if isinstance(lines, str) else list(lines)
        b.cursor_y = row
        b.cursor_x = col
        return b

    def test_inside_unclosed_string(self):
        self.assertTrue(_in_double_quoted(self.make_buffer('name = "ab', 10)))

    def test_after_closing_quote(self):
        self.assertFalse(_in_double_quoted(self.make_buffer('name = "ab"', 11)))

    def test_between_pair(self):
        self.assertTrue(_in_double_quoted(self.make_buffer('a = "x"', 6)))

    def test_empty_string_after_close(self):
        self.assertFalse(_in_double_quoted(self.make_buffer('a = ""', 6)))

    def test_escaped_quote_stays_inside(self):
        self.assertTrue(_in_double_quoted(self.make_buffer(r'a = "x\"y"', 9)))

    def test_double_inside_single_does_not_count(self):
        self.assertFalse(_in_double_quoted(self.make_buffer("a = 'it is \"fine\" c'", 20)))

    def test_single_quoted_string_not_suppressed(self):
        self.assertFalse(_in_double_quoted(self.make_buffer("a = 'xy", 7)))

    def test_triple_quoted_body_is_inside(self):
        self.assertTrue(_in_double_quoted(
            self.make_buffer(['a = """doc', ' text */'], 6, row=1)))

    def test_cursor_before_opening_quote(self):
        self.assertFalse(_in_double_quoted(self.make_buffer('prefix "text"', 3)))

    def test_inside_string_only_on_its_own_line(self):
        self.assertTrue(_in_double_quoted(
            self.make_buffer(['plain', 'x = "abc', 'z'], 10, row=1)))
        self.assertFalse(_in_double_quoted(
            self.make_buffer(['x = "abc"', ' z'], 3, row=1)))


class TestGhostWantedDoubleQuote(unittest.TestCase):
    def make_buffer(self, lines, col, row=0):
        b = Buffer()
        b.lines = [lines] if isinstance(lines, str) else list(lines)
        b.cursor_y = row
        b.cursor_x = col
        return b

    def test_no_ghost_inside_double_quoted_string(self):
        self.assertFalse(_ghost_wanted(self.make_buffer('tag = "val', 10)))

    def test_no_ghost_at_line_end_inside_string(self):
        self.assertFalse(_ghost_wanted(self.make_buffer('print("x', 9)))

    def test_ghost_returns_outside_string_after_close(self):
        self.assertTrue(_ghost_wanted(self.make_buffer('print("x") ; ', 14)))


class TestDrawGhost(unittest.TestCase):
    class FakeScr:
        def __init__(self):
            self.calls = []

        def addstr(self, row, col, text, attr):
            self.calls.append((row, col, text, attr))

    def make_ghost(self, text, y=0, x=0):
        import stdedit.codeium as codeium
        return codeium.Completion(text, y, x)

    def test_draws_at_cursor_when_anchored(self):
        g = self.make_ghost(" hello", 0, 1)
        s = self.FakeScr()
        b = Buffer()
        b.lines = ["a"]
        b.cursor_y = 0
        b.cursor_x = 1
        b.scroll_y = 0
        b.scroll_x = 0
        _draw_ghost(s, b, g, 0, 3, 40)
        self.assertEqual(s.calls, [(0, 4, " hello", curses.A_DIM)])

    def test_stale_anchor_skipped(self):
        g = self.make_ghost(" hi", 0, 1)
        s = self.FakeScr()
        b = Buffer()
        b.lines = ["aa"]
        b.cursor_y = 0
        b.cursor_x = 2
        _draw_ghost(s, b, g, 0, 3, 40)
        self.assertEqual(s.calls, [])

    def test_mid_line_skipped(self):
        g = self.make_ghost(" hi", 0, 1)
        s = self.FakeScr()
        b = Buffer()
        b.lines = ["abc"]
        b.cursor_x = 1
        _draw_ghost(s, b, g, 0, 3, 40)
        self.assertEqual(s.calls, [])


class TestDrawSuggestOverlay(unittest.TestCase):
    class FakeScr:
        def __init__(self):
            self.calls = []

        def addstr(self, row, col, text, attr):
            self.calls.append((row, col, text))

    def test_renders_box_and_candidates(self):
        s = self.FakeScr()
        sug = suggest.Suggestor()
        sug.open("python", {"gamma": 5}, "ga")
        b = Buffer()
        b.lines = ["ga"]
        b.cursor_y = 0
        b.cursor_x = 2
        b.scroll_y = 0
        b.scroll_x = 0
        _draw_suggest_overlay(s, sug, b, 0, 3, 40, 24, 80)
        joined = "".join(t for _, _, t in s.calls)
        self.assertIn("\u250c", joined)
        self.assertIn("\u2518", joined)
        self.assertIn("gamma", joined)

    def test_hidden_popup_noop(self):
        s = self.FakeScr()
        sug = suggest.Suggestor()
        b = Buffer()
        _draw_suggest_overlay(s, sug, b, 0, 3, 40, 24, 80)
        self.assertEqual(s.calls, [])


class TestFetchGhostText(unittest.TestCase):
    def test_fake_ghost_string(self):
        os.environ["STDEDIT_FAKE_GHOST"] = "import math"
        try:
            result = _fetch_ghost_text(None)
            self.assertIsNotNone(result)
            self.assertEqual(result.text, "import math")
        finally:
            del os.environ["STDEDIT_FAKE_GHOST"]

    def test_fake_ghost_none(self):
        os.environ["STDEDIT_FAKE_GHOST"] = "none"
        try:
            self.assertIsNone(_fetch_ghost_text(None))
        finally:
            del os.environ["STDEDIT_FAKE_GHOST"]


class TestRecentPicker(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest import mock
        from stdedit import tui, recent
        self._dir = tempfile.mkdtemp()
        self._recent = recent
        self._patch = mock.patch.object(tui.recent, "get_recent", return_value=[])
        self._get_recent = self._patch.start()
        self.picker = tui.RecentPicker()

    def tearDown(self):
        self._patch.stop()

    def existing_file(self, name="a.txt"):
        path = os.path.join(self._dir, name)
        open(path, "w").close()
        return path

    def test_open_keeps_only_existing_most_recent_first(self):
        keep1 = self.existing_file("b.txt")
        keep2 = self.existing_file("a.txt")
        self._get_recent.return_value = [os.path.join(self._dir, "gone.txt"),
                                         keep1, keep2]
        self.picker.open()
        self.assertTrue(self.picker.active)
        self.assertEqual(self.picker.entries, [keep1, keep2])
        self.assertEqual(self.picker.selected, 0)
        self.assertEqual(self.picker.selected_path(), keep1)

    def test_open_marks_active_and_resets_selection(self):
        self._get_recent.return_value = [self.existing_file("x.txt")]
        self.picker.open()
        self.picker.move_selection(1)
        self.picker.open()
        self.assertEqual(self.picker.selected, 0)

    def test_open_caps_entries(self):
        paths = [self.existing_file(f"f{i}.txt") for i in range(15)]
        self._get_recent.return_value = paths
        self.picker.open()
        self.assertEqual(len(self.picker.entries), RecentPicker.MAX_ENTRIES)
        self.assertEqual(self.picker.entries[0], paths[0])

    def test_empty_recent_produces_no_path(self):
        self._get_recent.return_value = []
        self.picker.open()
        self.assertEqual(self.picker.entries, [])
        self.assertIsNone(self.picker.selected_path())

    def test_move_selection_clamps_at_both_ends(self):
        self._get_recent.return_value = [self.existing_file(f"f{i}.txt")
                                         for i in range(3)]
        self.picker.open()
        self.picker.move_selection(-1)
        self.assertEqual(self.picker.selected, 0)
        self.picker.move_selection(5)
        self.assertEqual(self.picker.selected, 2)
        self.picker.move_selection(1)
        self.assertEqual(self.picker.selected, 2)

    def test_close_clears_active(self):
        self._get_recent.return_value = [self.existing_file("x.txt")]
        self.picker.open()
        self.picker.close()
        self.assertFalse(self.picker.active)

    def test_selected_path_follows_selection(self):
        p1 = self.existing_file("one.txt")
        p2 = self.existing_file("two.txt")
        self._get_recent.return_value = [p1, p2]
        self.picker.open()
        self.picker.move_selection(1)
        self.assertEqual(self.picker.selected_path(), p2)


class TestDrawRecentOverlay(unittest.TestCase):
    class FakeScr:
        def __init__(self):
            self.calls = []

        def addstr(self, row, col, text, attr):
            self.calls.append((row, col, text, attr))

    def test_draws_title_and_entries(self):
        p = RecentPicker()
        p.entries = ["/tmp/one.txt", "/tmp/two.txt"]
        p.selected = 0
        p.active = True
        s = self.FakeScr()
        _draw_recent_overlay(s, p, 24, 60)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("RECENT FILES", texts)
        self.assertIn("/tmp/one.txt", texts)
        self.assertIn("/tmp/two.txt", texts)
        self.assertIn("select", texts)

    def test_selected_entry_is_reversed(self):
        p = RecentPicker()
        p.entries = ["/tmp/one.txt", "/tmp/two.txt"]
        p.selected = 1
        s = self.FakeScr()
        _draw_recent_overlay(s, p, 24, 60)
        highlighted = [t for _, _, t, a in s.calls if a == curses.A_REVERSE]
        self.assertTrue(any("/tmp/two.txt" in t for t in highlighted))

    def test_empty_state_message(self):
        p = RecentPicker()
        p.entries = []
        p.selected = 0
        s = self.FakeScr()
        _draw_recent_overlay(s, p, 24, 60)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("No recent files", texts)

    def test_scroll_window_on_short_terminal(self):
        p = RecentPicker()
        p.entries = [f"/tmp/file{i}.txt" for i in range(10)]
        p.selected = 9
        s = self.FakeScr()
        _draw_recent_overlay(s, p, 10, 60)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("/tmp/file9.txt", texts)
        self.assertNotIn("/tmp/file0.txt", texts)


class TestDrawQuickOpenOverlay(unittest.TestCase):
    class FakeScr:
        def __init__(self):
            self.calls = []

        def getmaxyx(self):
            return (24, 80)

        def addstr(self, row, col, text, attr):
            self.calls.append((row, col, text, attr))

    def _qo(self, query, root):
        qo = QuickOpen(root)
        qo.visible = True
        qo.query = query
        qo.results = []
        qo.selected_idx = 0
        qo.loading = False
        qo.scan_error = None
        qo.capped = False
        qo.scoring = False
        return qo

    def test_folder_message_when_typed_dir_matches(self):
        qo = self._qo(_tempfile.mkdtemp(prefix="stdedit-qo-"), "/tmp")
        s = self.FakeScr()
        _draw_quick_open_overlay(s, qo)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("open this folder as project root", texts)

    def test_file_message_when_typed_file_matches(self):
        d = _tempfile.mkdtemp(prefix="stdedit-qo-")
        f = os.path.join(d, "target.py")
        with open(f, "w") as fh:
            fh.write("x")
        qo = self._qo(f, d)
        s = self.FakeScr()
        _draw_quick_open_overlay(s, qo)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("open typed path", texts)
        self.assertNotIn("as project root", texts)

    def test_no_matches_message(self):
        qo = self._qo("definitely-absent-xyz", "/tmp")
        s = self.FakeScr()
        _draw_quick_open_overlay(s, qo)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("No matches", texts)

    def test_folder_mode_title_and_hint(self):
        qo = self._qo(_tempfile.mkdtemp(prefix="stdedit-qo-"), "/tmp")
        qo.mode = "folders"
        s = self.FakeScr()
        _draw_quick_open_overlay(s, qo)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("Open Folder", texts)
        self.assertIn("open this folder as project root", texts)

    def test_folder_mode_empty_query_prompt(self):
        qo = self._qo("", "/tmp")
        qo.mode = "folders"
        s = self.FakeScr()
        _draw_quick_open_overlay(s, qo)
        texts = "".join(t for _, _, t, _ in s.calls)
        self.assertIn("Open Folder", texts)
        self.assertIn("Type to search folders", texts)


class TestQuickOpenCaret(unittest.TestCase):
    def _qo(self, query):
        qo = QuickOpen("/tmp")
        qo.visible = True
        qo.query = query
        qo.results = []
        qo.selected_idx = 0
        qo.loading = False
        qo.scan_error = None
        qo.capped = False
        qo.scoring = False
        return qo

    def test_caret_sits_after_typed_text_inside_box(self):
        qo = self._qo("abc")
        row, col = _quick_open_cursor_col(qo, 24, 80)
        _, top, left, inner_w, _, _ = _quick_open_geometry(qo, 24, 80)
        self.assertEqual(row, top + 1)  # input row
        self.assertEqual(col, left + 2 + len(qo.query))
        self.assertTrue(left < col < left + inner_w - 1)

    def test_typing_moves_caret_right(self):
        qo = self._qo("a")
        _, short = _quick_open_cursor_col(qo, 24, 80)
        qo.query = "ab"
        _, longer = _quick_open_cursor_col(qo, 24, 80)
        self.assertGreater(longer, short)

    def test_bare_pipe_over_empty_query(self):
        qo = self._qo("")
        _, col = _quick_open_cursor_col(qo, 24, 80)
        _, _, left, _, _, _ = _quick_open_geometry(qo, 24, 80)
        self.assertEqual(col, left + 2)  # " |" — the bare caret slot


class TestOverlaySignature(unittest.TestCase):
    def _qo(self, query=""):
        qo = QuickOpen("/tmp")
        qo.visible = True
        qo.query = query
        qo.results = []
        qo.selected_idx = 0
        qo.loading = False
        qo.scan_error = None
        qo.capped = False
        qo.scoring = False
        return qo

    def test_idle_frame_signature_is_stable(self):
        qo = self._qo("abc")
        rec = RecentPicker()
        first = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        second = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        self.assertEqual(first, second)

    def test_typing_changes_signature(self):
        qo = self._qo("abc")
        rec = RecentPicker()
        before = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        qo.query = "abcd"
        after = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        self.assertNotEqual(before, after)

    def test_results_and_selection_change_signature(self):
        qo = self._qo("t")
        rec = RecentPicker()
        before = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        qo.results = [(0.9, "/tmp/t.txt", True)]
        qo.selected_idx = 0
        mid = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        qo.selected_idx = 0
        qo.results = [(0.9, "/tmp/t.txt", True), (0.5, "/tmp/t2.py", False)]
        after = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        self.assertNotEqual(before, mid)
        self.assertNotEqual(mid, after)

    def test_overlay_open_close_changes_signature(self):
        qo = self._qo()
        rec = RecentPicker()
        closed = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        rec.active = True
        rec.entries = ["/tmp/a"]
        opened = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        self.assertNotEqual(closed, opened)
        rec.active = False
        reopened = _overlay_signature(qo, rec, False, 0, {}, False, 0, 0, 24, 80)
        self.assertEqual(reopened, closed)

    def test_settings_state_changes_signature(self):
        from stdedit import settings as settings_mod
        qo = self._qo()
        rec = RecentPicker()
        s1 = _overlay_signature(qo, rec, True, 0, {}, False, 0, 0, 24, 80)
        s2 = _overlay_signature(qo, rec, True, 3, {"THEME": True}, False, 0, 0, 24, 80)
        self.assertNotEqual(s1, s2)
        with mock.patch.object(settings_mod, "get", return_value=False):
            s3 = _overlay_signature(qo, rec, True, 3, {"THEME": True}, False, 0, 0, 24, 80)
        with mock.patch.object(settings_mod, "get", return_value=True):
            s4 = _overlay_signature(qo, rec, True, 3, {"THEME": True}, False, 0, 0, 24, 80)
        self.assertNotEqual(s3, s4)

    def test_help_scroll_changes_signature(self):
        qo = self._qo()
        rec = RecentPicker()
        s1 = _overlay_signature(qo, rec, False, 0, {}, True, 0, 10, 24, 80)
        s2 = _overlay_signature(qo, rec, False, 0, {}, True, 4, 10, 24, 80)
        self.assertNotEqual(s1, s2)


class TestForgetImagePixels(unittest.TestCase):
    def test_drops_pixels_and_error_keeps_view(self):
        st = {
            "pixels": [(106, 107, 109)] * 100,
            "width": 1432,
            "height": 711,
            "error": None,
            "decoded": True,
            "zoom": 2.5,
            "pan_x": 12,
            "pan_y": 4,
            "path": "/tmp/img.png",
        }
        _forget_image_pixels(st)
        self.assertIsNone(st["pixels"])
        self.assertFalse(st["decoded"])
        self.assertIsNone(st["error"])
        self.assertEqual(st["zoom"], 2.5)
        self.assertEqual(st["pan_x"], 12)
        self.assertEqual(st["pan_y"], 4)
        self.assertEqual(st["path"], "/tmp/img.png")


class TestStartupTree(unittest.TestCase):
    def setUp(self):
        self.tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _pathlib.Path(self.tmp.name)
        (self.project / "sub").mkdir()
        self.leaf = self.project / "sub" / "leaf.py"
        self.leaf.write_text("x=1\n")

    def test_reveals_existing_file(self):
        from stdedit.tui import _startup_tree
        from stdedit.explorer import FileExplorer
        explorer = FileExplorer(str(self.project))
        _startup_tree(explorer, str(self.leaf))
        self.assertTrue(explorer.visible)
        self.assertTrue(explorer.active)
        selected = explorer.get_selected()
        self.assertEqual(selected[2], str(self.leaf))

    def test_ignores_missing_file(self):
        from stdedit.tui import _startup_tree
        from stdedit.explorer import FileExplorer
        explorer = FileExplorer(str(self.project))
        _startup_tree(explorer, str(self.project / "nope.py"))
        self.assertEqual(explorer.selected_idx, 0)
        self.assertNotEqual(explorer.get_selected()[2], str(self.project / "nope.py"))

    def test_no_filename_is_safe(self):
        from stdedit.tui import _startup_tree
        from stdedit.explorer import FileExplorer
        explorer = FileExplorer(str(self.project))
        _startup_tree(explorer, None)
        self.assertEqual(explorer.selected_idx, 0)


class TestAutoSaveStep(unittest.TestCase):
    def _file_buf(self, text="hello\n"):
        tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = _pathlib.Path(tmp.name) / "doc.txt"
        path.write_text(text)
        buf = Buffer(str(path))
        return buf

    def test_idle_mode_saves_after_delay(self):
        buf = self._file_buf()
        buf.insert_char("x")
        saved, err = _autosave_step(
            buf, True, False, last_edit_time=0.0, last_save_time=0.0, now=6.0)
        self.assertTrue(saved)
        self.assertIsNone(err)
        self.assertFalse(buf.modified)

    def test_idle_mode_skips_before_delay(self):
        buf = self._file_buf()
        buf.insert_char("x")
        saved, err = _autosave_step(
            buf, True, False, last_edit_time=0.0, last_save_time=0.0, now=3.0)
        self.assertFalse(saved)
        self.assertIsNone(err)
        self.assertTrue(buf.modified)

    def test_idle_mode_skips_when_buffer_unmodified(self):
        buf = self._file_buf()
        saved, err = _autosave_step(
            buf, True, False, last_edit_time=0.0, last_save_time=0.0, now=60.0)
        self.assertFalse(saved)
        self.assertIsNone(err)

    def test_periodic_mode_saves_after_interval(self):
        buf = self._file_buf()
        buf.insert_char("x")
        saved, err = _autosave_step(
            buf, False, True, last_edit_time=0.0, last_save_time=0.0, now=31.0)
        self.assertTrue(saved)
        self.assertIsNone(err)
        self.assertFalse(buf.modified)

    def test_periodic_mode_skips_before_interval(self):
        buf = self._file_buf()
        buf.insert_char("x")
        saved, err = _autosave_step(
            buf, False, True, last_edit_time=0.0, last_save_time=0.0, now=10.0)
        self.assertFalse(saved)
        self.assertIsNone(err)

    def test_idle_takes_precedence_when_both_are_due(self):
        buf = self._file_buf()
        buf.insert_char("x")
        saved, err = _autosave_step(
            buf, True, True, last_edit_time=0.0, last_save_time=0.0, now=60.0)
        self.assertTrue(saved)
        self.assertIsNone(err)

    def test_no_filename_never_saves(self):
        buf = Buffer()
        buf.insert_char("x")
        buf.modified = True
        saved, err = _autosave_step(
            buf, True, True, last_edit_time=0.0, last_save_time=0.0, now=60.0)
        self.assertFalse(saved)
        self.assertIsNone(err)

    def test_oserror_is_reported_not_raised(self):
        buf = self._file_buf()
        buf.modified = True

        def boom():
            raise OSError("disk full")

        buf.save = boom
        saved, err = _autosave_step(
            buf, True, True, last_edit_time=0.0, last_save_time=0.0, now=60.0)
        self.assertFalse(saved)
        self.assertIn("disk full", err)

    def test_valueerror_is_reported_not_raised(self):
        buf = self._file_buf()
        buf.modified = True

        def boom():
            raise ValueError("No filename to save to")

        buf.save = boom
        saved, err = _autosave_step(
            buf, True, True, last_edit_time=0.0, last_save_time=0.0, now=60.0)
        self.assertFalse(saved)
        self.assertIn("No filename", err)


class TestAutoSaveOnEdit(unittest.TestCase):
    def test_saves_immediately_when_filename_set(self):
        tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = _pathlib.Path(tmp.name) / "doc.txt"
        path.write_text("hello\n")
        buf = Buffer(str(path))
        buf.lines = ["edited line"]
        buf.modified = True
        saved, err = _auto_save_on_edit(buf)
        self.assertTrue(saved)
        self.assertIsNone(err)
        self.assertFalse(buf.modified)
        self.assertEqual(path.read_text(), "edited line")

    def test_no_filename_returns_idle(self):
        buf = Buffer()
        buf.modified = True
        saved, err = _auto_save_on_edit(buf)
        self.assertFalse(saved)
        self.assertIsNone(err)

    def test_save_error_is_reported_not_raised(self):
        tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = _pathlib.Path(tmp.name) / "doc.txt"
        path.write_text("hello\n")
        buf = Buffer(str(path))

        def boom():
            raise OSError("read-only")

        buf.save = boom
        buf.modified = True
        saved, err = _auto_save_on_edit(buf)
        self.assertFalse(saved)
        self.assertIn("read-only", err)


class TestCtrl1Recognition(unittest.TestCase):
    """CSI-u Ctrl+1 must decode; a plain '1' must never be swallowed."""

    def _check(self, text):
        stdscr = _FakeStdscr(text)
        with mock.patch("curses.ungetch",
                        side_effect=lambda ch: stdscr.ungetch(ch)):
            ok = _is_ctrl_1(stdscr)
        return ok, stdscr._items

    def test_xterm_csi_u_ctrl_1(self):
        ok, remaining = self._check("[49;5u")
        self.assertTrue(ok)
        self.assertEqual(remaining, [])

    def test_kitty_csi_u_ctrl_1(self):
        ok, remaining = self._check("[49:5u")
        self.assertTrue(ok)
        self.assertEqual(remaining, [])

    def test_alternate_modified_1(self):
        ok, remaining = self._check("[1;5u")
        self.assertTrue(ok)
        self.assertEqual(remaining, [])

    def test_plain_one_is_not_ctrl_1_and_is_pushed_back(self):
        ok, remaining = self._check("1")
        self.assertFalse(ok)
        self.assertEqual(remaining, [ord("1")])

    def test_non_matching_csi_is_pushed_back_unchanged(self):
        ok, remaining = self._check("[11~")
        self.assertFalse(ok)
        self.assertEqual(remaining, [ord(c) for c in "[11~"])

    def test_bare_esc_followed_by_nothing(self):
        ok, remaining = self._check("")
        self.assertFalse(ok)
        self.assertEqual(remaining, [])


class TestLeaveToDashboard(unittest.TestCase):
    """The Save/Discard/Cancel gate must keep dirty work safe."""

    def _gate(self, buf, choice=None, save_error=None):
        stdscr = _FakeStdscr("")
        with mock.patch(
            "stdedit.tui._unsaved_changes_prompt", return_value=choice
        ):
            if save_error:
                def boom():
                    raise OSError(save_error)
                buf.save = boom
            return _leave_to_dashboard(
                stdscr, buf, render_unsaved=lambda t: None)

    def test_clean_buffer_is_allowed_immediately(self):
        buf = Buffer()
        self.assertEqual(self._gate(buf), (True, ""))

    def test_clean_buffer_missing_filename_still_allowed(self):
        buf = Buffer()
        self.assertEqual(self._gate(buf), (True, ""))

    def test_dirty_save_without_filename_blocked(self):
        buf = Buffer()
        buf.modified = True
        ok, msg = self._gate(buf, choice="save")
        self.assertFalse(ok)
        self.assertIn("No filename", msg)

    def test_dirty_save_persists_and_allows(self):
        tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = _pathlib.Path(tmp.name) / "doc.txt"
        path.write_text("hello\n")
        buf = Buffer(str(path))
        buf._lines = ["new", "text"]
        buf.modified = True
        ok, msg = self._gate(buf, choice="save")
        self.assertTrue(ok)
        self.assertEqual(path.read_text().splitlines(), ["new", "text"])

    def test_dirty_save_error_blocked(self):
        tmp = _tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = _pathlib.Path(tmp.name) / "doc.txt"
        path.write_text("hello\n")
        buf = Buffer(str(path))
        buf.modified = True
        ok, msg = self._gate(buf, choice="save", save_error="read-only")
        self.assertFalse(ok)
        self.assertIn("read-only", msg)

    def test_dirty_discard_allows_dashboard(self):
        buf = Buffer()
        buf.modified = True
        ok, msg = self._gate(buf, choice="discard")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_dirty_cancel_blocks_dashboard(self):
        buf = Buffer()
        buf.modified = True
        ok, msg = self._gate(buf, choice="cancel")
        self.assertFalse(ok)
        self.assertEqual(msg, "Cancelled")


if __name__ == "__main__":
    unittest.main()
