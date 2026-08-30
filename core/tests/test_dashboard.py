import os
import tempfile
import unittest

from stdedit.dashboard import action_key, action_count, layout, draw
from stdedit.quick_open import build_file_index


class DashboardLayoutTests(unittest.TestCase):
    def test_layout_never_exceeds_terminal_bounds(self):
        for width, height in [(24, 8), (40, 12), (60, 20), (80, 24), (120, 40), (160, 50)]:
            boxes = layout(height, width)
            for name, rect in boxes.items():
                if rect.w <= 0 or rect.h <= 0:
                    continue
                self.assertGreaterEqual(rect.x, 0, name)
                self.assertGreaterEqual(rect.y, 0, name)
                self.assertLessEqual(rect.x + rect.w, width, name)
                self.assertLessEqual(rect.y + rect.h, max(height, 8), name)

    def test_action_mapping(self):
        self.assertEqual(action_count(), 10)
        self.assertEqual(action_key(0), "F")
        self.assertEqual(action_key(1), "D")
        self.assertEqual(action_key(3), "N")
        self.assertEqual(action_key(5), "E")
        self.assertEqual(action_key(9), "Q")

    def test_action_keys_unique(self):
        from stdedit.dashboard import ACTIONS
        keys = [a[1] for a in ACTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(
            set(keys),
            {"F", "D", "O", "N", "R", "E", "S", "C", "H", "Q"})


class DashboardDrawTests(unittest.TestCase):
    def test_draw_renders_transient_message(self):
        from unittest import mock
        import stdedit.dashboard as db

        class Fake:
            def __init__(self, w, h):
                self.w, self.h = w, h
                self.calls = []

            def getmaxyx(self):
                return self.h, self.w

            def erase(self):
                pass

            def refresh(self):
                pass

            def addstr(self, *args):
                self.calls.append(args)

            def addch(self, *args):
                pass

            def hline(self, *args):
                pass

            def vline(self, *args):
                pass

        fake = Fake(90, 30)
        with mock.patch.object(db, "init_colors"), \
                mock.patch.object(db.curses, "ACS_HLINE", "-", create=True), \
                mock.patch.object(db.curses, "ACS_VLINE", "|", create=True):
            draw(fake, 0, 1.0, "10 MiB", message="Folder dialog cancelled")
        bottom = fake.calls[-1][2]
        self.assertIn("Folder dialog cancelled", bottom)
        self.assertIn("Enter selects", bottom)
        fake2 = Fake(90, 30)
        with mock.patch.object(db, "init_colors"), \
                mock.patch.object(db.curses, "ACS_HLINE", "-", create=True), \
                mock.patch.object(db.curses, "ACS_VLINE", "|", create=True):
            draw(fake2, 0, 1.0, "10 MiB")
        self.assertNotIn("Folder dialog cancelled", fake2.calls[-1][2])


class HomeSearchScopeTests(unittest.TestCase):
    def test_excluded_roots_are_not_indexed(self):
        with tempfile.TemporaryDirectory() as td:
            keep = os.path.join(td, "keep.txt")
            excluded = os.path.join(td, "yuki-code", "main.py")
            os.makedirs(os.path.dirname(excluded))
            open(keep, "w", encoding="utf-8").close()
            open(excluded, "w", encoding="utf-8").close()
            files = build_file_index(td, exclude_roots=[os.path.dirname(excluded)])
            self.assertIn(os.path.abspath(keep), files)
            self.assertNotIn(os.path.abspath(excluded), files)

    def test_hidden_junk_dirs_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "visible.txt"), "w", encoding="utf-8").close()
            hidden = os.path.join(td, ".cache", "junk.txt")
            os.makedirs(os.path.dirname(hidden))
            open(hidden, "w", encoding="utf-8").close()
            files = build_file_index(td)
            self.assertIn(os.path.abspath(os.path.join(td, "visible.txt")), files)
            self.assertNotIn(os.path.abspath(hidden), files)


if __name__ == "__main__":
    unittest.main()
