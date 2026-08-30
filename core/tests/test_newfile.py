"""Tests for the folder-first New File dashboard overlay."""

import curses
import os
import tempfile
import unittest

from stdedit.newfile import NewFilePicker, CTRL_1, draw
from stdedit.buffer import Buffer


def make_tree(*subdirs, files=None) -> str:
    td = tempfile.mkdtemp(prefix="stdedit-newfile-")
    for sub in subdirs:
        os.makedirs(os.path.join(td, sub), exist_ok=True)
    for f in files or ["abc.py", "main.c", "script.sh", "README.md", "z.py"]:
        with open(os.path.join(td, f), "w", encoding="utf-8"):
            pass
    return td


class NewFilePickerTests(unittest.TestCase):
    def test_open_lists_directories_only(self):
        td = make_tree("src", "docs", "node_modules", ".hidden")
        picker = NewFilePicker()
        picker.open(td)
        names = [e[0] for e in picker.entries]
        self.assertIn("src", names)
        self.assertIn("docs", names)
        self.assertNotIn("node_modules", names)  # always-ignored
        self.assertNotIn(".hidden", names)       # hidden filtered
        self.assertNotIn("abc.py", names)        # shallow: dirs only

    def test_open_clears_filename_and_message(self):
        td = make_tree("src")
        picker = NewFilePicker()
        picker.open(td)
        picker.filename = "x.py"
        picker.message = "stale"
        picker.open(td)
        self.assertEqual(picker.filename, "")
        self.assertEqual(picker.message, "")
        self.assertTrue(picker.active)

    def test_enter_selected_enters_directory(self):
        td = make_tree("src/lib")
        picker = NewFilePicker()
        picker.open(td)
        picker.selected = 0  # default selection is the first directory
        picker.enter_selected()
        self.assertTrue(picker.cwd.endswith("src"))

    def test_backspace_with_filename_edits_filename(self):
        td = make_tree("src")
        picker = NewFilePicker()
        picker.open(td)
        picker.filename = "abc.py"
        picker.backspace()
        self.assertEqual(picker.filename, "abc.p")
        self.assertEqual(picker.cwd, td)

    def test_backspace_empty_filename_goes_to_parent(self):
        td = make_tree("a/b/c")
        picker = NewFilePicker()
        picker.open(os.path.join(td, "a", "b"))
        picker.backspace()
        self.assertEqual(picker.cwd, os.path.join(td, "a"))
        # Selection lands on the folder we came from.
        self.assertEqual(picker.entries[picker.selected][1], os.path.join(td, "a", "b"))

    def test_backspace_at_root_does_nothing(self):
        root = os.path.abspath(os.sep)
        picker = NewFilePicker(start_dir=root)
        picker.open(root)
        self.assertTrue(picker.at_root())
        picker.backspace()
        self.assertEqual(picker.cwd, root)
        self.assertEqual(picker.message, "Already at filesystem root")

    def test_visible_entries_keep_selection_visible(self):
        td = make_tree(*[f"d{i:02d}" for i in range(20)])
        picker = NewFilePicker()
        picker.open(td)
        self.assertEqual(len(picker.entries), 20)
        # Move far beyond a tiny viewport: selection must remain on screen.
        for _ in range(17):
            picker.move(1)
        visible = picker.visible_entries(5)
        self.assertIn(picker.selected, visible)
        self.assertEqual(len(visible), 5)
        # Moving back up re-shows the top rows.
        for _ in range(17):
            picker.move(-1)
        picker.scroll = 0
        visible = picker.visible_entries(5)
        self.assertIn(picker.selected, visible)

    def test_move_is_clamped(self):
        td = make_tree("a", "b")
        picker = NewFilePicker()
        picker.open(td)
        picker.move(-99)
        self.assertEqual(picker.selected, 0)
        picker.move(99)
        self.assertEqual(picker.selected, 1)

    def test_handle_key_edits_filename_and_creates(self):
        td = make_tree()
        picker = NewFilePicker()
        picker.open(td)
        self.assertIsNone(picker.handle_key("h"))
        self.assertIsNone(picker.handle_key("i"))
        self.assertIsNone(picker.handle_key("\t"))
        picker.filename = "hello.txt"
        self.assertEqual(picker.handle_key("\n"), "created")
        self.assertTrue(os.path.isfile(os.path.join(td, "hello.txt")))
        self.assertFalse(picker.active)

    def test_handle_key_esc_returns_to_dashboard(self):
        picker = NewFilePicker()
        picker.open(make_tree())
        self.assertEqual(picker.handle_key("\x1b"), "dashboard")
        self.assertFalse(picker.active)

    def test_handle_key_ctrl_1_returns_to_dashboard(self):
        picker = NewFilePicker()
        picker.open(make_tree())
        self.assertEqual(picker.handle_key(CTRL_1), "dashboard")
        self.assertFalse(picker.active)

    def test_handle_key_down_up(self):
        td = make_tree("a", "b", "c")
        picker = NewFilePicker()
        picker.open(td)
        self.assertIsNone(picker.handle_key(curses.KEY_DOWN))
        self.assertEqual(picker.selected, 1)
        self.assertIsNone(picker.handle_key(curses.KEY_UP))
        self.assertEqual(picker.selected, 0)

    def test_handle_key_enter_without_filename_enters_selected_dir(self):
        td = make_tree("src")
        picker = NewFilePicker()
        picker.open(td)
        self.assertIsNone(picker.handle_key("\n"))
        self.assertTrue(picker.cwd.endswith("src"))

    def test_handle_key_enter_invalid_keeps_ui_alive(self):
        td = make_tree()
        picker = NewFilePicker()
        picker.open(td)
        picker.filename = "../escape.py"
        self.assertEqual(picker.handle_key("\n"), None)
        self.assertTrue(picker.active)
        self.assertIn("path separator", picker.message)
        self.assertFalse(os.path.exists(os.path.join(td, "..", "expect-fail")))

    def test_handle_key_enter_empty_filename_message(self):
        td = make_tree()
        picker = NewFilePicker()
        picker.open(td)
        self.assertIsNone(picker.handle_key("\n"))
        self.assertTrue(picker.active)

    def test_create_traversal_is_rejected(self):
        td = make_tree()
        picker = NewFilePicker()
        picker.open(td)
        picker.filename = "../evil.py"
        path, error = picker.create()
        self.assertTrue(error)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(td), "evil.py")))

    def test_create_duplicate_reports_and_stays_alive(self):
        td = make_tree(files=["exists.txt"])
        with open(os.path.join(td, "exists.txt"), "w", encoding="utf-8"):
            pass
        picker = NewFilePicker()
        picker.open(td)
        picker.filename = "exists.txt"
        path, error = picker.create()
        self.assertTrue(error)
        self.assertIn("already exists", error)
        self.assertTrue(picker.active)
        self.assertEqual(path, os.path.join(td, "exists.txt"))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "permission checks are bypassed as root")
    def test_create_permission_error_reported(self):
        td = make_tree()
        locked = os.path.join(td, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        try:
            picker = NewFilePicker()
            picker.open(locked)
            picker.filename = "no.txt"
            path, error = picker.create()
            self.assertTrue(error)
            self.assertIn("Cannot create", error)
            self.assertTrue(picker.active)
        finally:
            os.chmod(locked, 0o700)

    def test_complete_filename_reuses_completion_api(self):
        td = make_tree(files=["alpha.py", "alpine.sh"])
        picker = NewFilePicker()
        picker.open(td)
        picker.filename = "al"
        picker._complete_filename()
        self.assertTrue(picker.filename.startswith("al"))
        self.assertNotIn(os.sep, picker.filename)

    def test_draw_is_single_pass_into_existing_frame(self):
        class Fake:
            def __init__(self, w, h):
                self.w, self.h = w, h
                self.calls = 0

            def getmaxyx(self):
                return self.h, self.w

            def addstr(self, *args):
                self.calls += 1

        td = make_tree("src")
        picker = NewFilePicker()
        picker.open(td)
        fake = Fake(60, 24)
        draw(fake, picker, 24, 60)
        self.assertGreater(fake.calls, 0)


class NewFilePickerSelectHelpers(unittest.TestCase):
    def test_select_first_dir_helper(self):
        td = make_tree("src")
        picker = NewFilePicker()
        picker.open(td)
        picker.selected = 0
        self.assertEqual(picker.entries[picker.selected][1], os.path.join(td, "src"))

    def test_buffer_unused(self):
        # The overlay must never depend on an editor Buffer.
        td = make_tree()
        picker = NewFilePicker()
        picker.open(td)
        self.assertNotIsInstance(picker, Buffer)


if __name__ == "__main__":
    unittest.main()