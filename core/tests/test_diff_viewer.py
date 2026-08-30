"""Tests for the diff viewer overlay."""
import unittest

from stdedit.diff_viewer import DiffViewer, diff_viewer_key


_SAMPLE_DIFF = """\
diff --git a/foo.py b/foo.py
index abc1234..def5678 100644
--- a/foo.py
+++ b/foo.py
@@ -1,5 +1,6 @@
 line1
+added line
 line2
-line3
+changed line
 line4"""


class TestDiffViewerParse(unittest.TestCase):
    def test_parse_header_lines(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF)
        headers = [t for t, _ in v.lines if t == "header"]
        self.assertGreater(len(headers), 0)

    def test_parse_hunk_lines(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF)
        hunks = [t for t, _ in v.lines if t == "hunk"]
        self.assertEqual(len(hunks), 1)

    def test_parse_add_lines(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF)
        adds = [text for t, text in v.lines if t == "add"]
        self.assertEqual(len(adds), 2)  # +added line, +changed line

    def test_parse_del_lines(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF)
        dels = [text for t, text in v.lines if t == "del"]
        self.assertEqual(len(dels), 1)  # -line3

    def test_parse_context_lines(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF)
        ctx = [t for t, _ in v.lines if t == "context"]
        self.assertGreater(len(ctx), 0)

    def test_empty_diff(self):
        v = DiffViewer()
        v.load("")
        self.assertEqual(v.lines, [])

    def test_load_resets_scroll(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF)
        v.scroll(5)
        v.load(_SAMPLE_DIFF)
        self.assertEqual(v.scroll_y, 0)

    def test_title_set(self):
        v = DiffViewer()
        v.load(_SAMPLE_DIFF, title="foo.py")
        self.assertEqual(v.title, "foo.py")


class TestDiffViewerScroll(unittest.TestCase):
    def setUp(self):
        self.v = DiffViewer()
        self.v.load(_SAMPLE_DIFF)

    def test_scroll_down(self):
        self.v.scroll(1)
        self.assertEqual(self.v.scroll_y, 1)

    def test_scroll_up(self):
        self.v.scroll(5)
        self.v.scroll(-2)
        self.assertEqual(self.v.scroll_y, 3)

    def test_scroll_clamps_to_zero(self):
        self.v.scroll(-5)
        self.assertEqual(self.v.scroll_y, 0)

    def test_scroll_clamps_to_max(self):
        self.v.scroll(999)
        self.assertLessEqual(self.v.scroll_y, len(self.v.lines) - 1)

    def test_page_down(self):
        self.v.page_down(5)
        self.assertEqual(self.v.scroll_y, 5)

    def test_page_up(self):
        self.v.page_down(10)
        self.v.page_up(5)
        self.assertEqual(self.v.scroll_y, 5)

    def test_home(self):
        self.v.scroll(10)
        self.v.home()
        self.assertEqual(self.v.scroll_y, 0)

    def test_end(self):
        self.v.end(5)
        self.assertEqual(self.v.scroll_y, max(0, len(self.v.lines) - 5))


class TestDiffViewerKey(unittest.TestCase):
    def setUp(self):
        self.v = DiffViewer()
        self.v.load(_SAMPLE_DIFF, title="test")
        self.ph = 10  # page height

    def test_q_exits(self):
        result = diff_viewer_key(self.v, "q", self.ph)
        self.assertFalse(result)

    def test_esc_exits(self):
        result = diff_viewer_key(self.v, "\x1b", self.ph)
        self.assertFalse(result)

    def test_down_scrolls_down(self):
        diff_viewer_key(self.v, "down", self.ph)
        self.assertEqual(self.v.scroll_y, 1)

    def test_up_scrolls_up(self):
        self.v.scroll(3)
        diff_viewer_key(self.v, "up", self.ph)
        self.assertEqual(self.v.scroll_y, 2)

    def test_space_pages_down(self):
        diff_viewer_key(self.v, " ", self.ph)
        self.assertEqual(self.v.scroll_y, self.ph)

    def test_u_pages_up(self):
        max_scroll = max(0, len(self.v.lines) - self.ph)
        self.v.scroll(max_scroll)  # go to end
        diff_viewer_key(self.v, "u", self.ph)
        self.assertEqual(self.v.scroll_y, max(0, max_scroll - self.ph))

    def test_g_home(self):
        self.v.scroll(5)
        diff_viewer_key(self.v, "g", self.ph)
        self.assertEqual(self.v.scroll_y, 0)

    def test_G_end(self):
        diff_viewer_key(self.v, "G", self.ph)
        expected = max(0, len(self.v.lines) - self.ph)
        self.assertEqual(self.v.scroll_y, expected)

    def test_unknown_key_still_consumed(self):
        result = diff_viewer_key(self.v, "x", self.ph)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
