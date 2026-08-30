import os
import tempfile
import unittest

from stdedit.buffer import Buffer


class TestBasicEditing(unittest.TestCase):
    def test_insert_char(self):
        b = Buffer()
        for ch in "hi":
            b.insert_char(ch)
        self.assertEqual(b.lines, ["hi"])
        self.assertEqual((b.cursor_y, b.cursor_x), (0, 2))

    def test_insert_newline_splits_line(self):
        b = Buffer()
        for ch in "hello":
            b.insert_char(ch)
        b.move_to(2, 0)
        b.insert_newline()
        self.assertEqual(b.lines, ["he", "llo"])
        self.assertEqual((b.cursor_y, b.cursor_x), (1, 0))

    def test_auto_indent_on_newline(self):
        b = Buffer()
        b.lines = ["    if True:"]
        b.move_to(len(b.lines[0]), 0)
        b.insert_newline()
        self.assertEqual(b.lines[1], "        ")  # inherited + one Python level
        self.assertEqual(b.cursor_x, 8)

    def test_auto_indent_after_python_block_header(self):
        for source in ("def greeting():", "for item in items:", "while ready:", "class Greeting:"):
            b = Buffer(tab_size=4, use_spaces=True)
            b.lines = [source]
            b.move_to(len(source), 0)
            b.insert_newline()
            self.assertEqual(b.lines, [source, "    "])
            self.assertEqual(b.cursor_x, 4)

    def test_newline_inside_block_keeps_block_indent(self):
        b = Buffer(tab_size=4, use_spaces=True)
        b.lines = ["def greeting():", "    print('hi')"]
        b.move_to(len(b.lines[1]), 1)
        b.insert_newline()
        self.assertEqual(b.lines[2], "    ")
        self.assertEqual(b.cursor_x, 4)

    def test_auto_indent_tab_mode(self):
        b = Buffer(tab_size=4, use_spaces=False)
        b.lines = ["if ready:"]
        b.move_to(len(b.lines[0]), 0)
        b.insert_newline()
        self.assertEqual(b.lines[1], "\t")
        self.assertEqual(b.cursor_x, 1)

    def test_backspace_joins_lines(self):
        b = Buffer()
        b.lines = ["foo", "bar"]
        b.move_to(0, 1)
        b.backspace()
        self.assertEqual(b.lines, ["foobar"])
        self.assertEqual((b.cursor_y, b.cursor_x), (0, 3))

    def test_delete_char_forward(self):
        b = Buffer()
        b.lines = ["abc"]
        b.move_to(1, 0)
        b.delete_char()
        self.assertEqual(b.lines, ["ac"])

    def test_delete_char_joins_next_line(self):
        b = Buffer()
        b.lines = ["foo", "bar"]
        b.move_to(3, 0)
        b.delete_char()
        self.assertEqual(b.lines, ["foobar"])


class TestSelectionAndClipboard(unittest.TestCase):
    def test_selection_and_copy(self):
        b = Buffer()
        b.lines = ["hello world"]
        b.move_to(0, 0)
        b.move_to(5, 0, extend_selection=True)
        self.assertTrue(b.has_selection())
        self.assertEqual(b.selected_text(), "hello")
        self.assertEqual(b.copy(), "hello")

    def test_cut_removes_and_stores(self):
        b = Buffer()
        b.lines = ["hello world"]
        b.move_to(0, 0)
        b.move_to(6, 0, extend_selection=True)
        b.cut()
        self.assertEqual(b.lines, ["world"])
        self.assertEqual(b.clipboard, "hello ")

    def test_paste_single_line(self):
        b = Buffer()
        b.lines = ["world"]
        b.move_to(0, 0)
        b.paste("hello ")
        self.assertEqual(b.lines, ["hello world"])

    def test_paste_multiline(self):
        b = Buffer()
        b.lines = ["ac"]
        b.move_to(1, 0)
        b.paste("X\nY")
        self.assertEqual(b.lines, ["aX", "Yc"])
        self.assertEqual((b.cursor_y, b.cursor_x), (1, 1))

    def test_paste_multiline_rebases_indent_on_blank_line(self):
        b = Buffer(tab_size=4, use_spaces=True)
        b.lines = ["def greeting():", "    "]
        b.move_to(4, 1)
        b.paste("print('hello')\nif ready:\n    print('ready')")
        self.assertEqual(b.lines, [
            "def greeting():",
            "    print('hello')",
            "    if ready:",
            "        print('ready')",
        ])
        self.assertEqual((b.cursor_y, b.cursor_x), (3, 22))

    def test_paste_multiline_preserves_indent_when_not_on_blank_line(self):
        b = Buffer(tab_size=4, use_spaces=True)
        b.lines = ["x = "]
        b.move_to(4, 0)
        b.paste("a\n    b")
        self.assertEqual(b.lines, ["x = a", "    b"])

    def test_multiline_selection_delete(self):
        b = Buffer()
        b.lines = ["one", "two", "three"]
        b.move_to(0, 1)  # (x=0, y=1) -> start of "two"
        b.move_to(2, 2, extend_selection=True)  # (x=2, y=2) -> "th" of "three"
        # Selects from row1 col0 ("two") through row2 col2 ("th" of "three"),
        # so "two" and the "th" prefix of "three" are removed.
        b.delete_selection()
        self.assertEqual(b.lines, ["one", "ree"])


class TestUndoRedo(unittest.TestCase):
    def test_undo_redo_typing_coalesces(self):
        b = Buffer()
        for ch in "hello":
            b.insert_char(ch)
        self.assertEqual(b.lines, ["hello"])
        b.undo()
        self.assertEqual(b.lines, [""])
        b.redo()
        self.assertEqual(b.lines, ["hello"])

    def test_undo_after_distinct_actions(self):
        b = Buffer()
        b.insert_char("a")
        b.insert_newline()
        b.insert_char("b")
        self.assertEqual(b.lines, ["a", "b"])
        b.undo()  # undo insert_char('b')
        self.assertEqual(b.lines, ["a", ""])
        b.undo()  # undo insert_newline
        self.assertEqual(b.lines, ["a"])
        b.undo()  # undo insert_char('a')
        self.assertEqual(b.lines, [""])
        self.assertFalse(b.undo())

    def test_redo_cleared_by_new_edit(self):
        b = Buffer()
        b.insert_char("a")
        b.undo()
        b.insert_char("b")
        self.assertFalse(b.redo())


class TestIndentAndTabs(unittest.TestCase):
    def test_insert_tab_as_spaces(self):
        b = Buffer(tab_size=4, use_spaces=True)
        b.insert_tab()
        self.assertEqual(b.lines, ["    "])

    def test_insert_tab_literal(self):
        b = Buffer(tab_size=4, use_spaces=False)
        b.insert_tab()
        self.assertEqual(b.lines, ["\t"])

    def test_indent_selection(self):
        b = Buffer(tab_size=2, use_spaces=True)
        b.lines = ["a", "b"]
        b.move_to(0, 0)
        b.move_to(1, 1, extend_selection=True)
        b.indent_selection()
        self.assertEqual(b.lines, ["  a", "  b"])


class TestSelectWordAt(unittest.TestCase):
    def test_selects_word(self):
        b = Buffer()
        b.lines = ["hello world"]
        b.select_word_at(0, 2)
        self.assertEqual(b.selection_anchor, (0, 0))
        self.assertEqual(b.cursor_x, 5)
        self.assertEqual(b.selected_text(), "hello")

    def test_selects_second_word(self):
        b = Buffer()
        b.lines = ["hello world"]
        b.select_word_at(0, 7)
        self.assertEqual(b.selection_anchor, (0, 6))
        self.assertEqual(b.cursor_x, 11)
        self.assertEqual(b.selected_text(), "world")

    def test_selects_punctuation_group(self):
        b = Buffer()
        b.lines = ["a -- b"]
        b.select_word_at(0, 3)
        self.assertEqual(b.selection_anchor, (0, 1))
        self.assertEqual(b.cursor_x, 5)
        self.assertEqual(b.selected_text(), " -- ")

    def test_empty_line_no_selection(self):
        b = Buffer()
        b.lines = ["hello"]
        b.select_word_at(0, 10)
        self.assertIsNone(b.selection_anchor)

    def test_out_of_range_no_selection(self):
        b = Buffer()
        b.lines = ["hello"]
        b.select_word_at(5, 0)
        self.assertIsNone(b.selection_anchor)


class TestSelectLineAt(unittest.TestCase):
    def test_selects_entire_line(self):
        b = Buffer()
        b.lines = ["hello world"]
        b.select_line_at(0)
        self.assertEqual(b.selection_anchor, (0, 0))
        self.assertEqual(b.cursor_x, 11)
        self.assertEqual(b.selected_text(), "hello world")

    def test_empty_line(self):
        b = Buffer()
        b.lines = [""]
        b.select_line_at(0)
        self.assertEqual(b.selection_anchor, (0, 0))
        self.assertEqual(b.cursor_x, 0)

    def test_out_of_range_no_selection(self):
        b = Buffer()
        b.lines = ["hello"]
        b.select_line_at(5)
        self.assertIsNone(b.selection_anchor)


class TestLanguageIndent(unittest.TestCase):
    def test_configure_sets_tab_size_and_patterns(self):
        b = Buffer()
        b.configure_for_language("python")
        self.assertEqual(b.tab_size, 4)
        self.assertIsNotNone(b._increase_re)
        self.assertIsNone(b._decrease_re)

        b2 = Buffer()
        b2.configure_for_language("javascript")
        self.assertEqual(b2.tab_size, 2)
        self.assertIsNotNone(b2._increase_re)
        self.assertIsNotNone(b2._decrease_re)

    def test_python_colon_indents(self):
        b = Buffer()
        b.configure_for_language("python")
        b.lines = ["if True:"]
        b.move_to(len("if True:"), 0)
        b.insert_newline()
        self.assertEqual(b.lines, ["if True:", "    "])
        self.assertEqual(b.cursor_x, 4)

    def test_javascript_brace_indents(self):
        b = Buffer(tab_size=2)
        b.configure_for_language("javascript")
        b.lines = ["function foo() {"]
        b.move_to(len("function foo() {"), 0)
        b.insert_newline()
        self.assertEqual(b.lines, ["function foo() {", "  "])
        self.assertEqual(b.cursor_x, 2)

    def test_decrease_on_closer_after_cursor(self):
        b = Buffer(tab_size=4)
        b.configure_for_language("c")
        b.lines = ["    int x = 0;}"]
        b.move_to(14, 0)
        b.insert_newline()
        # Cursor is right before `}`, so the new line should get
        # decreased indent (4 - 4 = 0).
        self.assertEqual(b.lines[0], "    int x = 0;")
        self.assertEqual(b.lines[1], "}")
        self.assertEqual(b.cursor_x, 0)

    def test_yaml_two_space_indent(self):
        b = Buffer()
        b.configure_for_language("yaml")
        self.assertEqual(b.tab_size, 2)
        b.lines = ["key:"]
        b.move_to(len("key:"), 0)
        b.insert_newline()
        self.assertEqual(b.lines, ["key:", "  "])
        self.assertEqual(b.cursor_x, 2)

    def test_smart_dedent_on_brace(self):
        b = Buffer(tab_size=4)
        b.configure_for_language("c")
        b.lines = ["    "]
        b.move_to(4, 0)
        b.smart_dedent_on_char("}")
        self.assertEqual(b.lines[0], "}")
        self.assertEqual(b.cursor_x, 1)

    def test_smart_dedent_skips_nonempty_line(self):
        b = Buffer(tab_size=4)
        b.configure_for_language("c")
        b.lines = ["    return 0;"]
        b.move_to(11, 0)
        result = b.smart_dedent_on_char("}")
        self.assertFalse(result)
        self.assertEqual(b.lines[0], "    return 0;")

    def test_smart_dedent_noop_without_decrease_re(self):
        b = Buffer(tab_size=4)
        b.lines = ["    }"]
        b.move_to(0, 0)
        result = b.smart_dedent_on_char("}")
        self.assertFalse(result)


class TestFileIO(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.txt")
            b = Buffer()
            b.lines = ["line one", "line two", "line three"]
            b.save(path)

            b2 = Buffer(path)
            self.assertEqual(b2.lines, ["line one", "line two", "line three"])

    def test_crlf_detected_and_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crlf.txt")
            with open(path, "wb") as f:
                f.write(b"a\r\nb\r\n")
            b = Buffer(path)
            self.assertEqual(b.lines, ["a", "b", ""])
            self.assertEqual(b.newline, "\r\n")
            b.save()
            with open(path, "rb") as f:
                raw = f.read()
            self.assertIn(b"\r\n", raw)

    def test_utf8_bom_detected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bom.txt")
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbfhello")
            b = Buffer(path)
            self.assertEqual(b.lines, ["hello"])
            self.assertEqual(b.encoding, "utf-8-sig")


class TestCursorMovement(unittest.TestCase):
    def test_move_left_wraps_to_previous_line(self):
        b = Buffer()
        b.lines = ["foo", "bar"]
        b.move_to(0, 1)
        b.move_cursor(dx=-1)
        self.assertEqual((b.cursor_y, b.cursor_x), (0, 3))

    def test_move_right_wraps_to_next_line(self):
        b = Buffer()
        b.lines = ["foo", "bar"]
        b.move_to(3, 0)
        b.move_cursor(dx=1)
        self.assertEqual((b.cursor_y, b.cursor_x), (1, 0))

    def test_update_scroll_follows_cursor(self):
        b = Buffer()
        b.lines = [str(i) for i in range(100)]
        b.move_to(0, 50)
        b.update_scroll(viewport_height=20, viewport_width=80)
        self.assertEqual(b.scroll_y, 31)  # 50 - 20 + 1


class TestUndoMemoryBudget(unittest.TestCase):
    def test_history_is_bounded_by_memory_budget(self):
        from stdedit.undo import UndoManager
        manager = UndoManager(max_history=500, max_bytes=1024)
        lines = ["x" * 5000]
        manager.checkpoint(lines, 0, 0)
        self.assertEqual(manager.history_count, 0)
        self.assertEqual(manager.history_bytes, 0)

    def test_history_is_bounded_by_count(self):
        from stdedit.undo import UndoManager
        manager = UndoManager(max_history=2, max_bytes=1024 * 1024)
        for i in range(5):
            manager.checkpoint([str(i)], i, 0)
        self.assertLessEqual(manager.history_count, 2)

class TestBracketsAndLargeFiles(unittest.TestCase):
    def test_auto_close_and_skip(self):
        b = Buffer()
        self.assertTrue(b.auto_close_bracket("("))
        self.assertEqual(b.lines, ["()"])
        self.assertEqual(b.cursor_x, 1)
        self.assertTrue(b.skip_closer(")"))
        self.assertEqual(b.cursor_x, 2)

    def test_matching_brackets_same_and_nested_lines(self):
        b = Buffer()
        b.lines = ["def f():", "    value = ({'x': [1, 2]})"]
        b.move_to(12, 1)  # on opening paren
        match = b.matching_bracket()
        self.assertEqual(match, (1, 26))
        b.move_to(26, 1)  # before closing paren
        self.assertEqual(b.matching_bracket(), (1, 12))

    def test_large_file_mode_disables_snapshot_checkpoints(self):
        b = Buffer()
        b.large_file_mode = True
        for ch in "abcdef":
            b.insert_char(ch)
        self.assertFalse(b.undo())
        self.assertTrue(b.modified)

    def test_zero_threshold_keeps_undo_enabled(self):
        b = Buffer(large_file_threshold=0)
        b.insert_char("a")
        self.assertTrue(b.undo())

class TestCompactLargeFileStore(unittest.TestCase):
    def test_large_file_uses_compact_store_and_edits(self):
        from stdedit.storage.compact import CompactLines
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "large.txt")
            with open(path, "wb") as f:
                f.write((b"alpha\n" * 200000))
            b = Buffer(path, large_file_threshold=1024)
            from stdedit.storage.mapped import MappedLines
            self.assertIsInstance(b.lines, MappedLines)
            self.assertEqual(b.lines[0], "alpha")
            b.move_to(5, 0)
            b.insert_char("!")
            self.assertIsInstance(b.lines, CompactLines)
            self.assertEqual(b.lines[0], "alpha!")
            b.move_to(0, 1)
            b.backspace()
            self.assertEqual(b.lines[0], "alpha!alpha")

    def test_large_file_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "large.txt")
            with open(path, "wb") as f:
                f.write(b"a\nb\nc\n")
            b = Buffer(path, large_file_threshold=1)
            b.lines[1] = "B"
            b.save()
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"a\nB\nc\n")


if __name__ == "__main__":
    unittest.main()
