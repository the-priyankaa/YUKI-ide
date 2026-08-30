"""Tests for the dashboard Extensions overlay (discovery-only)."""

import curses
import os
import tempfile
import unittest

from stdedit.extview import ExtensionsView, EMPTY_STATE, draw
from stdedit.extensions.loader import discover


class ExtensionsViewTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="stdedit-extview-")
        self.ext_dir = os.path.join(self.td, ".stdedit", "extensions")
        os.makedirs(self.ext_dir)
        # Isolate discovery from the user's real HOME/STDEDIT_EXTENSIONS.
        self._old_home = os.environ.get("HOME")
        self._old_env = os.environ.get("STDEDIT_EXTENSIONS")
        os.environ["HOME"] = self.td
        os.environ["STDEDIT_EXTENSIONS"] = os.path.join(self.td, ".no-ext")

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        if self._old_env is None:
            os.environ.pop("STDEDIT_EXTENSIONS", None)
        else:
            os.environ["STDEDIT_EXTENSIONS"] = self._old_env

    def _write(self, name, source="from stdedit import *\nname='x'\n"):
        path = os.path.join(self.ext_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        return path

    def test_open_list_uses_discover(self):
        path = self._write("alpha.py")
        self._write("beta.py")
        view = ExtensionsView(cwd=self.td)
        view.open()
        st = discover(self.td)
        self.assertTrue(view.active)
        self.assertEqual(len(view.entries), len(st))
        self.assertEqual(sorted(n for n, _ in view.entries),
                         ["alpha", "beta"])
        self.assertIn(str(path), {p for _, p in view.entries})

    def test_open_never_imports_extension_modules(self):
        # A syntactically broken module must still be listed, because the
        # view never executes extension code.
        path = self._write("broken.py", "this is not valid python (((")
        view = ExtensionsView(cwd=self.td)
        view.open()
        self.assertIn("broken", [n for n, _ in view.entries])
        self.assertIn(str(path), {p for _, p in view.entries})

    def test_empty_state_message_verbatim(self):
        view = ExtensionsView(cwd=self.td)
        view.open()
        self.assertEqual(view.entries, [])
        self.assertEqual(EMPTY_STATE, "No extensions available at the moment")

    def test_close(self):
        view = ExtensionsView(cwd=self.td)
        view.open()
        view.close()
        self.assertFalse(view.active)

    def test_move_and_visible_entries(self):
        for i in range(10):
            self._write(f"ext{i}.py")
        view = ExtensionsView(cwd=self.td)
        view.open()
        for _ in range(9):
            view.move(1)
        view.move(1)  # clamped
        self.assertEqual(view.selected, 9)
        visible = view.visible_entries(4)
        self.assertIn(view.selected, visible)
        self.assertEqual(len(visible), 4)
        view.move(-99)
        self.assertEqual(view.selected, 0)

    def test_directory_count(self):
        view = ExtensionsView(cwd=self.td)
        self.assertGreaterEqual(view.directory_count(), 1)

    def test_draw_empty_state(self):
        class Fake:
            def __init__(self, w, h):
                self.w, self.h = w, h
                self.calls = 0

            def getmaxyx(self):
                return self.h, self.w

            def addstr(self, *args):
                self.calls += 1

        view = ExtensionsView(cwd=self.td)
        view.open()
        fake = Fake(60, 24)
        draw(fake, view, 24, 60)
        self.assertGreater(fake.calls, 0)

    def test_draw_populated(self):
        for i in range(3):
            self._write(f"ext{i}.py")
        class Fake:
            def __init__(self, w, h):
                self.w, self.h = w, h
                self.calls = 0

            def getmaxyx(self):
                return self.h, self.w

            def addstr(self, *args):
                self.calls += 1

        view = ExtensionsView(cwd=self.td)
        view.open()
        fake = Fake(60, 24)
        draw(fake, view, 24, 60)
        self.assertGreater(fake.calls, 0)


if __name__ == "__main__":
    unittest.main()