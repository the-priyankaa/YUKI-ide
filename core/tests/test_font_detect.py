"""Tests for font_detect — system monospace font detection."""

import unittest
from stdedit import font_detect


class TestFontDetect(unittest.TestCase):
    def test_detect_returns_list(self):
        fonts = font_detect.detect_monospace_fonts()
        self.assertIsInstance(fonts, list)

    def test_detect_returns_nonempty(self):
        fonts = font_detect.detect_monospace_fonts()
        self.assertGreater(len(fonts), 0)

    def test_detect_strings_are_nonempty(self):
        fonts = font_detect.detect_monospace_fonts()
        for f in fonts:
            self.assertIsInstance(f, str)
            self.assertGreater(len(f), 0)

    def test_sanitize_simple(self):
        self.assertEqual(font_detect.sanitize_font_key("Hack"), "font_hack")

    def test_sanitize_spaces(self):
        self.assertEqual(font_detect.sanitize_font_key("DejaVu Sans Mono"), "font_dejavu_sans_mono")

    def test_sanitize_special_chars(self):
        result = font_detect.sanitize_font_key("Font v2.0!")
        self.assertTrue(result.startswith("font_"))
        self.assertNotIn(" ", result)
        self.assertNotIn(".", result)
        self.assertNotIn("!", result)

    def test_font_keys_and_labels_same_length(self):
        keys, labels = font_detect.font_keys_and_labels()
        self.assertEqual(len(keys), len(labels))

    def test_font_keys_start_with_font(self):
        keys, _ = font_detect.font_keys_and_labels()
        for k in keys:
            self.assertTrue(k.startswith("font_"))

    def test_font_labels_unique(self):
        _, labels = font_detect.font_keys_and_labels()
        self.assertEqual(len(labels), len(set(labels)))


if __name__ == "__main__":
    unittest.main()
