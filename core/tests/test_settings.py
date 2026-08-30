"""Tests for stdedit.settings — persistence, defaults, and toggle behaviour."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import stdedit.settings as settings

_TMP_DIR = tempfile.mkdtemp(prefix="stdedit-test-settings-")


def setUpModule():
    """Sandbox the config layer so tests never touch the real settings file."""
    settings.CONFIG_DIR = Path(_TMP_DIR)
    settings.CONFIG_FILE = Path(_TMP_DIR) / "settings.json"


def tearDownModule():
    settings.CONFIG_DIR = Path.home() / ".config" / "stdedit"
    settings.CONFIG_FILE = settings.CONFIG_DIR / "settings.json"


class TestDefaults(unittest.TestCase):
    """Verify the module provides sane defaults when no config file exists."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_all_auto_save_off_by_default(self):
        with mock.patch.object(settings, "CONFIG_FILE", Path("/nonexistent")):
            settings._load()
            self.assertTrue(settings.get("auto_save_off"))
            self.assertFalse(settings.get("auto_save_idle"))
            self.assertFalse(settings.get("auto_save_periodic"))
            self.assertFalse(settings.get("auto_save_on_edit"))

    def test_any_auto_save_false_by_default(self):
        with mock.patch.object(settings, "CONFIG_FILE", Path("/nonexistent")):
            settings._load()
            self.assertFalse(settings.any_auto_save())

    def test_unknown_key_returns_false(self):
        self.assertFalse(settings.get("no_such_key"))


class TestRoundTrip(unittest.TestCase):
    """Toggle, persist, re-load — verify the value survives."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._file = self._dir / "settings.json"
        self._patch_config = mock.patch.object(
            settings, "CONFIG_DIR", self._dir
        )
        self._patch_file = mock.patch.object(
            settings, "CONFIG_FILE", self._file
        )
        self._patch_config.start()
        self._patch_file.start()

    def tearDown(self):
        self._patch_file.stop()
        self._patch_config.stop()
        self._tmp.cleanup()

    def test_toggle_persists_and_reloads(self):
        settings._load()
        self.assertTrue(settings.get("auto_save_off"))
        settings.toggle_radio("auto_save_idle")
        self.assertTrue(settings.get("auto_save_idle"))
        # Re-load from disk
        settings._load()
        self.assertTrue(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_off"))

    def test_set_persists(self):
        settings._load()
        settings.toggle_radio("auto_save_periodic")
        self.assertTrue(self._file.exists())
        settings._load()
        self.assertTrue(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_off"))

    def test_toggle_back_to_false(self):
        settings._load()
        settings.toggle("auto_save_on_edit")   # True
        settings.toggle("auto_save_on_edit")   # False
        settings._load()
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_json_file_is_valid(self):
        settings._load()
        settings.toggle("auto_save_idle")
        data = json.loads(self._file.read_text())
        self.assertIsInstance(data, dict)
        self.assertIn("auto_save_idle", data)

    def test_unrelated_keys_ignored_on_load(self):
        self._file.write_text('{"auto_save_off": false, "auto_save_idle": true, "junk": 42}\n')
        settings._load()
        self.assertTrue(settings.get("auto_save_idle"))
        # junk should not cause an error


class TestCorruptFile(unittest.TestCase):
    """Corrupt or unreadable config files should not crash the editor."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._file = self._dir / "settings.json"
        self._patch_config = mock.patch.object(
            settings, "CONFIG_DIR", self._dir
        )
        self._patch_file = mock.patch.object(
            settings, "CONFIG_FILE", self._file
        )
        self._patch_config.start()
        self._patch_file.start()

    def tearDown(self):
        self._patch_file.stop()
        self._patch_config.stop()
        self._tmp.cleanup()

    def test_corrupt_json_uses_defaults(self):
        self._file.write_text("{bad json!!!")
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_non_dict_json_uses_defaults(self):
        self._file.write_text('[1, 2, 3]')
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))

    def test_missing_file_uses_defaults(self):
        # No file written
        settings._load()
        self.assertFalse(settings.get("auto_save_idle"))


class TestWriteFailure(unittest.TestCase):
    """Write errors should be silently ignored (read-only fs, etc.)."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_toggle_succeeds_even_if_write_fails(self):
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError):
            result = settings.toggle("auto_save_idle")
            self.assertTrue(result)
            self.assertTrue(settings.get("auto_save_idle"))

    def test_set_succeeds_even_if_write_fails(self):
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError):
            settings.set("auto_save_idle", True)
            self.assertTrue(settings.get("auto_save_idle"))


class TestLabels(unittest.TestCase):
    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_labels_match_defaults(self):
        keys = {k for k, _ in settings.LABELS if k is not None}
        self.assertEqual(keys, set(settings._DEFAULTS.keys()))


class TestRadioGroup(unittest.TestCase):
    """toggle_radio: mutual exclusion within radio groups."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)

    def test_toggle_radio_turns_on_and_clears_others(self):
        settings.toggle_radio("auto_save_idle")
        self.assertTrue(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_off"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_already_active_turns_off(self):
        settings.toggle_radio("auto_save_idle")   # ON
        settings.toggle_radio("auto_save_idle")   # OFF
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_off"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_cross_activation(self):
        settings.toggle_radio("auto_save_idle")    # idle ON
        settings.toggle_radio("auto_save_periodic")  # periodic ON, idle OFF
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_off"))
        self.assertTrue(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_non_radio_key_uses_plain_toggle(self):
        settings.toggle_radio("no_such_key")
        self.assertTrue(settings.get("no_such_key"))

    def test_is_radio_key(self):
        self.assertTrue(settings.is_radio_key("auto_save_off"))
        self.assertTrue(settings.is_radio_key("auto_save_idle"))
        self.assertTrue(settings.is_radio_key("auto_save_periodic"))
        self.assertTrue(settings.is_radio_key("auto_save_on_edit"))
        self.assertTrue(settings.is_radio_key("suggestions_off"))
        self.assertTrue(settings.is_radio_key("suggestions_on"))
        self.assertTrue(settings.is_radio_key("codeium_on"))
        self.assertFalse(settings.is_radio_key("no_such_key"))


class TestStrictBooleans(unittest.TestCase):
    """Only literal JSON booleans may set a bool setting."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._file = self._dir / "settings.json"
        self._patch_config = mock.patch.object(settings, "CONFIG_DIR", self._dir)
        self._patch_file = mock.patch.object(settings, "CONFIG_FILE", self._file)
        self._patch_config.start()
        self._patch_file.start()

    def tearDown(self):
        self._patch_file.stop()
        self._patch_config.stop()
        self._tmp.cleanup()

    def test_non_bool_values_ignored(self):
        self._file.write_text(json.dumps({
            "auto_save_idle": 1,
            "suggestions_off": "yes",
            "codeium_on": "false",
            "auto_save_on_edit": None,
        }))
        settings._load()
        # All stay at their defaults; nothing became truthy.
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertTrue(settings.get("suggestions_off"))   # default is on
        self.assertFalse(settings.get("codeium_on"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_real_bool_is_respected(self):
        self._file.write_text(json.dumps({
            "suggestions_off": False,
            "codeium_on": True,
            "auto_save_idle": False,
        }))
        settings._load()
        self.assertTrue(settings.get("codeium_on"))
        self.assertFalse(settings.get("suggestions_off"))
        self.assertFalse(settings.get("auto_save_idle"))


class TestSuggestionsRadioGroup(unittest.TestCase):
    """SUGGESTIONS options are mutually exclusive and default to Off."""

    def setUp(self):
        settings._settings = dict(settings._DEFAULTS)
        self._tmp = Path(tempfile.mkdtemp()) / "settings.json"
        self._mgr = mock.patch.object(settings, "CONFIG_FILE", self._tmp)
        self._mgr.start()

    def tearDown(self):
        self._mgr.stop()

    def test_default_is_off(self):
        self.assertTrue(settings.get("suggestions_off"))
        self.assertFalse(settings.get("suggestions_on"))
        self.assertFalse(settings.get("codeium_on"))

    def test_enabling_auto_suggest_clears_others(self):
        settings.toggle_radio("suggestions_on")
        self.assertTrue(settings.get("suggestions_on"))
        self.assertFalse(settings.get("suggestions_off"))
        self.assertFalse(settings.get("codeium_on"))

    def test_enabling_codeium_clears_others(self):
        settings.toggle_radio("codeium_on")
        self.assertTrue(settings.get("codeium_on"))
        self.assertFalse(settings.get("suggestions_off"))
        self.assertFalse(settings.get("suggestions_on"))

    def test_switching_keeps_exactly_one_on(self):
        settings.toggle_radio("suggestions_on")
        settings.toggle_radio("codeium_on")
        active = [k for k in ("suggestions_off", "suggestions_on", "codeium_on")
                  if settings.get(k)]
        self.assertEqual(active, ["codeium_on"])

    def test_toggling_active_option_back_to_off(self):
        settings.toggle_radio("suggestions_on")
        settings.toggle_radio("suggestions_on")
        self.assertFalse(any(settings.get(k) for k in
                             ("suggestions_off", "suggestions_on", "codeium_on")))

    def test_load_normalizes_all_three_on(self):
        settings._settings = {"suggestions_off": True, "suggestions_on": True,
                              "codeium_on": True}
        settings._enforce_radio_groups()
        self.assertEqual(
            [k for k in ("suggestions_off", "suggestions_on", "codeium_on")
             if settings._settings.get(k)],
            ["suggestions_off"])

    def test_enforce_on_load_fixes_legacy_multi(self):
        """Legacy config with multiple ON → load keeps only the first."""
        settings._settings["auto_save_off"] = True
        settings._settings["auto_save_idle"] = True
        settings._settings["auto_save_periodic"] = True
        settings._settings["auto_save_on_edit"] = True
        settings._enforce_radio_groups()
        self.assertTrue(settings.get("auto_save_off"))
        self.assertFalse(settings.get("auto_save_idle"))
        self.assertFalse(settings.get("auto_save_periodic"))
        self.assertFalse(settings.get("auto_save_on_edit"))

    def test_toggle_radio_persists_and_reloads(self):
        settings.toggle_radio("auto_save_on_edit")
        settings._save()
        settings._load()
        self.assertTrue(settings.get("auto_save_on_edit"))
        self.assertFalse(settings.get("auto_save_idle"))

    def test_any_auto_save_only_checks_radio_group(self):
        settings.toggle_radio("auto_save_periodic")
        self.assertTrue(settings.any_auto_save())
        settings.toggle_radio("auto_save_periodic")  # OFF
        self.assertFalse(settings.any_auto_save())

    def test_any_auto_save_excludes_off(self):
        settings.set("auto_save_off", True)
        self.assertFalse(settings.any_auto_save())
        settings.set("auto_save_idle", True)
        self.assertTrue(settings.any_auto_save())


class TestFontFamily(unittest.TestCase):
    def setUp(self):
        for fk in settings._font_keys:
            settings.set(fk, False)
        settings.set(settings._font_keys[0], True)

    def test_first_font_is_default(self):
        first_key = settings._font_keys[0]
        self.assertTrue(settings.get(first_key))

    def test_other_fonts_are_off(self):
        first_key = settings._font_keys[0]
        for fk in settings._font_keys[1:]:
            self.assertFalse(settings.get(fk), f"{fk} should be off by default")

    def test_font_radio_group(self):
        second_key = settings._font_keys[1]
        settings.toggle_radio(second_key)
        self.assertTrue(settings.get(second_key))
        self.assertFalse(settings.get(settings._font_keys[0]))

    def test_font_switch(self):
        k1 = settings._font_keys[1]
        k2 = settings._font_keys[2]
        settings.toggle_radio(k1)
        self.assertTrue(settings.get(k1))
        settings.toggle_radio(k2)
        self.assertTrue(settings.get(k2))
        self.assertFalse(settings.get(k1))

    def test_font_toggle_off(self):
        k = settings._font_keys[1]
        settings.toggle_radio(k)
        self.assertTrue(settings.get(k))
        settings.toggle_radio(k)  # OFF
        self.assertFalse(settings.get(k))
        self.assertFalse(settings.get(settings._font_keys[0]))

    def test_font_all_exclusive(self):
        for fk in settings._font_keys[1:]:
            settings.toggle_radio(fk)
            active = [k for k in settings._font_keys if settings.get(k)]
            self.assertEqual(len(active), 1, f"Expected 1 active, got {active} for {fk}")
            self.assertEqual(active[0], fk)

    def test_get_active_font_name(self):
        name = settings.get_active_font_name()
        self.assertIsInstance(name, str)
        self.assertTrue(len(name) > 0)

    def test_get_active_font_key(self):
        key = settings.get_active_font_key()
        self.assertIn(key, settings._font_keys)

    def test_font_key_to_label_matches(self):
        for fk, fl in zip(settings._font_keys, settings._font_labels):
            self.assertEqual(settings._KEY_TO_FONT_NAME[fk], fl)

    def test_labels_contain_font_section(self):
        section_headers = [label for key, label in settings.LABELS if key is None]
        self.assertIn("FONT FAMILY", section_headers)


class TestTheme(unittest.TestCase):
    def setUp(self):
        for tk in settings._theme_keys:
            settings.set(tk, False)
        settings.set(settings._theme_keys[0], True)

    def test_first_theme_is_default(self):
        self.assertIn("default", settings.themes.THEME_ORDER)
        first_key = settings._theme_keys[0]
        self.assertTrue(settings.get(first_key))

    def test_other_themes_are_off(self):
        for tk in settings._theme_keys[1:]:
            self.assertFalse(settings.get(tk), f"{tk} should be off by default")

    def test_theme_radio_group(self):
        second_key = settings._theme_keys[1]
        settings.toggle_radio(second_key)
        self.assertTrue(settings.get(second_key))
        self.assertFalse(settings.get(settings._theme_keys[0]))

    def test_theme_switch(self):
        k1 = settings._theme_keys[1]
        k2 = settings._theme_keys[2]
        settings.toggle_radio(k1)
        self.assertTrue(settings.get(k1))
        settings.toggle_radio(k2)
        self.assertTrue(settings.get(k2))
        self.assertFalse(settings.get(k1))

    def test_get_active_theme_name(self):
        name = settings.get_active_theme_name()
        self.assertIn(name, settings.themes.theme_names())

    def test_get_active_theme_key(self):
        key = settings.get_active_theme_key()
        self.assertIn(key, settings._theme_keys)

    def test_labels_contain_theme_section(self):
        section_headers = [label for key, label in settings.LABELS if key is None]
        self.assertIn("THEME", section_headers)

    def test_theme_section_before_font(self):
        idx_theme = [i for i, (k, _) in enumerate(settings.LABELS) if k is None and _ == "THEME"][0]
        idx_font = [i for i, (k, _) in enumerate(settings.LABELS) if k is None and _ == "FONT FAMILY"][0]
        self.assertLess(idx_theme, idx_font)


if __name__ == "__main__":
    unittest.main()
