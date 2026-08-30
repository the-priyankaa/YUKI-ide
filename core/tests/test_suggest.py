"""Tests for the local auto-suggestion engine (test_suggest)."""
import unittest

from stdedit import suggest
from stdedit.languages import schema


class WordAtTests(unittest.TestCase):
    def test_cursor_after_identifier(self):
        self.assertEqual(suggest.word_at("def foo", 7), (4, "foo"))

    def test_cursor_at_end_not_identifier(self):
        self.assertEqual(suggest.word_at("def  ", 5), (5, ""))

    def test_cursor_at_col_zero(self):
        self.assertEqual(suggest.word_at("abc", 0), (0, ""))

    def test_mid_word(self):
        self.assertEqual(suggest.word_at("hello world", 6), (6, ""))
        self.assertEqual(suggest.word_at("ab_cd", 3), (0, "ab_"))

    def test_unicode_colons_break_word(self):
        self.assertEqual(suggest.word_at("x::foo", 6), (3, "foo"))


class IdentifierWordsTests(unittest.TestCase):
    def test_counts_and_dedup(self):
        c = suggest.identifier_words(["alpha beta alpha", "_gamma"])
        self.assertEqual(c["alpha"], 2)
        self.assertEqual(c["beta"], 1)
        self.assertEqual(c["_gamma"], 1)

    def test_ignores_digits_only(self):
        c = suggest.identifier_words(["42 1abc2"])
        self.assertNotIn("42", c)
        self.assertIn("abc2", c)

    def test_scan_limit(self):
        lines = ["word"] * 2500
        c = suggest.identifier_words(lines, limit=2000)
        self.assertEqual(c["word"], 2000)


class CandidatesTests(unittest.TestCase):
    def test_keywords_preferred(self):
        doc = {"system": 100, "select": 100}
        kw = schema.language_keywords("python")
        out = suggest.candidates("python", doc, "im")
        self.assertEqual(out[0], "import")
        self.assertIn("import", kw)

    def test_doc_words_ranked(self):
        doc = {"initial": 5, "init_limit": 3, "inited": 3}
        out = suggest.candidates("python", doc, "init")
        self.assertEqual(out[:3], ["initial", "init_limit", "inited"])

    def test_case_insensitive_prefix(self):
        out = suggest.candidates("python", {"IMPORTANT": 1}, "imp")
        self.assertIn("IMPORTANT", out)

    def test_empty_prefix(self):
        self.assertEqual(suggest.candidates("python", {"a": 1}, ""), [])

    def test_max_items(self):
        doc = {f"w{i}": i for i in range(50)}
        out = suggest.candidates("python", doc, "w1", max_items=10)
        self.assertLessEqual(len(out), 10)


class SuggestorTests(unittest.TestCase):
    def setUp(self):
        self.s = suggest.Suggestor()

    def test_open_sets_visible_and_query(self):
        self.s.open("python", {"gamma": 1}, "ga")
        self.assertTrue(self.s.visible)
        self.assertEqual(self.s.query, "ga")
        self.assertEqual(self.s.candidates, ["gamma"])

    def test_open_no_matches_closes(self):
        self.s.open("python", {}, "zzz")
        self.assertFalse(self.s.visible)
        self.assertEqual(self.s.candidates, [])

    def test_move_wraps(self):
        self.s.open("python", {"zap": 1, "zoo": 1}, "z")
        self.assertTrue(self.s.visible)
        self.assertEqual(len(self.s.candidates), 2)
        self.s.move(1)
        self.assertEqual(self.s.selected, 1)
        self.s.move(1)
        self.assertEqual(self.s.selected, 0)

    def test_close_resets(self):
        self.s.open("python", {"foo": 1}, "fo")
        self.s.close()
        self.assertFalse(self.s.visible)
        self.assertEqual(self.s.selected, 0)
        self.assertEqual(self.s.candidates, [])

    def test_accept_suffix_skips_prefix(self):
        self.s.open("python", {"foobar": 1}, "foo")
        self.s.selected = 0
        self.assertEqual(self.s.accept_suffix(), "bar")

    def test_accept_suffix_full_equals_prefix(self):
        self.s.open("python", {}, "import")
        self.s.selected = 0
        self.assertEqual(self.s.accept_suffix(), "")

    def test_selected_text_empty_when_no_visible(self):
        self.assertEqual(self.s.selected_text(), "")


class LanguageKeywordsTests(unittest.TestCase):
    def test_nonempty_for_coding_languages(self):
        for lang in ("python", "javascript", "typescript", "c", "cpp",
                     "java", "rust", "go", "css", "shell", "sql"):
            self.assertTrue(schema.language_keywords(lang), lang)

    def test_plaintext_empty(self):
        self.assertEqual(schema.language_keywords("plaintext"), [])

    def test_python_has_core_keywords(self):
        kw = set(schema.language_keywords("python"))
        for needed in ("import", "def", "class", "return", "if", "from"):
            self.assertIn(needed, kw)


if __name__ == "__main__":
    unittest.main()