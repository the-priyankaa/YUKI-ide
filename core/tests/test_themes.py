"""Tests for the built-in theme system."""

import unittest
from unittest import mock

from stdedit import themes


class TestThemeDefinitions(unittest.TestCase):
    def test_all_themes_present(self):
        for name in themes.THEME_ORDER:
            self.assertIn(name, themes.THEMES)

    def test_no_missing_roles(self):
        self.assertEqual(themes.validate_themes(), [])

    def test_every_theme_has_name(self):
        for name in themes.THEME_ORDER:
            self.assertIsInstance(themes.THEMES[name]["name"], str)

    def test_syntax_colors_are_pairs(self):
        for name in themes.THEME_ORDER:
            for role, color in themes.THEMES[name]["syntax"].items():
                self.assertEqual(len(color), 2, f"{name}:{role}")

    def test_git_colors_pair(self):
        for name in themes.THEME_ORDER:
            for role, color in themes.THEMES[name]["git"].items():
                self.assertEqual(len(color), 2, f"{name}:{role}")

    def test_diff_colors_are_pairs(self):
        for name in themes.THEME_ORDER:
            for role, color in themes.THEMES[name]["diff"].items():
                self.assertEqual(len(color), 2, f"{name}:{role}")


class TestThemeHelpers(unittest.TestCase):
    def test_theme_names_and_keys_same_length(self):
        keys = themes.theme_keys()
        labels = themes.theme_names()
        self.assertEqual(len(keys), len(labels))
        self.assertEqual(len(keys), len(themes.THEME_ORDER))

    def test_keys_start_with_theme(self):
        for k in themes.theme_keys():
            self.assertTrue(k.startswith("theme_"))

    def test_sanitize_simple(self):
        self.assertEqual(themes.sanitize_theme_key("monokai"), "theme_monokai")

    def test_sanitize_spaces(self):
        self.assertEqual(themes.sanitize_theme_key("Solarized Dark"),
                         "theme_solarized_dark")

    def test_syntax_color_default(self):
        fg, bg = themes.syntax_color("default", "keyword")
        self.assertEqual(bg, -1)

    def test_git_color_has_value(self):
        self.assertEqual(themes.git_color("default", "M"), 3)

    def test_new_themes_present(self):
        for tid in ["tokyo_night", "gruvbox_dark", "catppuccin_mocha",
                    "rose_pine", "github_light", "zenburn", "everforest", "ayu"]:
            self.assertIn(tid, themes.THEME_ORDER)
            self.assertIn("theme_" + tid, themes.theme_keys())
            self.assertIn(tid, themes.THEMES)
            self.assertTrue(themes.THEMES[tid]["name"])

    def test_new_theme_names(self):
        self.assertEqual(themes.THEMES["tokyo_night"]["name"], "Tokyo Night")
        self.assertEqual(themes.THEMES["gruvbox_dark"]["name"], "Gruvbox Dark")
        self.assertEqual(themes.THEMES["ayu"]["name"], "Ayu")


class TestResolve(unittest.TestCase):
    def test_resolve_256_unchanged(self):
        fg, bg = themes._resolve(197, -1, colors=256)
        self.assertEqual((fg, bg), (197, -1))

    def test_resolve_16_folds(self):
        fg, bg = themes._resolve(196, -1, colors=8)  # xterm bright red
        self.assertEqual(fg, themes.curses.COLOR_RED)
        self.assertEqual(bg, -1)

    def test_resolve_background_folds(self):
        fg, bg = themes._resolve(196, 46, colors=8)  # red fg, green bg
        self.assertEqual(fg, themes.curses.COLOR_RED)
        self.assertEqual(bg, themes.curses.COLOR_GREEN)


class TestResolveId(unittest.TestCase):
    def test_apply_theme_takes_display_name(self):
        self.assertIsNotNone(themes.git_color("Monokai", "M"))
        fg, bg = themes.syntax_color("One Dark", "keyword")
        self.assertEqual(fg, 203)

    def test_resolve_theme_id(self):
        self.assertEqual(themes.resolve_theme_id("Monokai"), "monokai")
        self.assertEqual(themes.resolve_theme_id("monokai"), "monokai")
        self.assertEqual(themes.resolve_theme_id("theme_monokai"), "monokai")
        self.assertEqual(themes.resolve_theme_id("nope"), "default")
        self.assertEqual(themes.resolve_theme_id(None), "default")
        self.assertEqual(themes.resolve_theme_id(""), "default")


class TestApplyTheme(unittest.TestCase):
    def test_apply_theme_noop_without_colors(self):
        """apply_theme must not touch curses when color is unavailable."""
        with mock.patch("stdedit.themes.curses.has_colors", return_value=False), \
             mock.patch("stdedit.themes.curses.init_pair",
                        side_effect=AssertionError("init_pair called")):
            themes.apply_theme("monokai")

    def test_apply_theme_unknown_name_falls_back_to_default(self):
        with mock.patch("stdedit.themes.curses.has_colors", return_value=True), \
             mock.patch("stdedit.themes.curses.init_pair") as init_pair:
            themes.apply_theme("no_such_theme")
            self.assertGreater(init_pair.call_count, 0)


if __name__ == "__main__":
    unittest.main()