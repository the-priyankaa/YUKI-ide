"""Editor settings — persistent JSON-backed toggle store.

Settings are saved to ``~/.config/stdedit/settings.json`` so they survive
restarts.  If the file is missing or corrupt, sensible defaults are used.
Write failures (read-only filesystem, etc.) are silently ignored so the
editor always works — it just won't remember across sessions.
"""

from __future__ import annotations

import json

from pathlib import Path

from . import font_detect
from . import themes

CONFIG_DIR = Path.home() / ".config" / "stdedit"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# --- Auto-save keys (static) ---
_AUTO_SAVE_KEYS = ["auto_save_off", "auto_save_idle", "auto_save_periodic", "auto_save_on_edit"]

# --- Font family keys (dynamic from system) ---
_font_keys, _font_labels = font_detect.font_keys_and_labels()

# --- Theme keys (dynamic from built-in themes) ---
_theme_keys, _theme_labels = themes.theme_keys(), themes.theme_names()

# Build _DEFAULTS: auto-save + first font ON + default theme ON
_DEFAULTS: dict[str, bool] = {
    "auto_save_off": True,
    "auto_save_idle": False,
    "auto_save_periodic": False,
    "auto_save_on_edit": False,
    "suggestions_off": True,
    "suggestions_on": False,
    "codeium_on": False,
}
for i, fk in enumerate(_font_keys):
    _DEFAULTS[fk] = (i == 0)
for i, tk in enumerate(_theme_keys):
    _DEFAULTS[tk] = (i == 0)

# Build LABELS
LABELS: list[tuple[str | None, str]] = [
    (None, "AUTO-SAVE"),
    ("auto_save_off", "Auto-save: off"),
    ("auto_save_idle", "Auto-save: on idle (5s)"),
    ("auto_save_periodic", "Auto-save: every 30s"),
    ("auto_save_on_edit", "Auto-save: on every edit"),
    (None, ""),
    (None, "THEME"),
]
for tk, tl in zip(_theme_keys, _theme_labels):
    LABELS.append((tk, tl))
LABELS.append((None, ""))
LABELS.append((None, "FONT FAMILY"))
for fk, fl in zip(_font_keys, _font_labels):
    LABELS.append((fk, fl))
LABELS.append((None, ""))
LABELS.append((None, "SUGGESTIONS"))
LABELS.append(("suggestions_off", "Suggestions: off"))
LABELS.append(("suggestions_on", "Auto-suggest"))
LABELS.append(("codeium_on", "AI inline (Codeium)"))

# Build RADIO_GROUPS
RADIO_GROUPS: dict[str, list[str]] = {
    "auto_save": list(_AUTO_SAVE_KEYS),
    "theme": list(_theme_keys),
    "font_family": list(_font_keys),
    "suggestions": ["suggestions_off", "suggestions_on", "codeium_on"],
}

# Build reverse lookup: key -> group name
_KEY_TO_GROUP: dict[str, str] = {}
for _gname, _gkeys in RADIO_GROUPS.items():
    for _k in _gkeys:
        _KEY_TO_GROUP[_k] = _gname

# Build reverse lookup: key -> display name
_KEY_TO_FONT_NAME: dict[str, str] = dict(zip(_font_keys, _font_labels))

# Build reverse lookup: theme key -> display name
_KEY_TO_THEME_NAME: dict[str, str] = dict(zip(_theme_keys, _theme_labels))

_settings: dict[str, bool] = dict(_DEFAULTS)


def _load() -> None:
    """Load settings from disk, falling back to defaults."""
    global _settings
    _settings = dict(_DEFAULTS)
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in _DEFAULTS:
                if key in data and isinstance(data[key], bool):
                    _settings[key] = data[key]
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _enforce_radio_groups()


def _enforce_radio_groups() -> None:
    """If multiple keys in a radio group are ON, keep only the first."""
    for _gname, _gkeys in RADIO_GROUPS.items():
        active = [k for k in _gkeys if _settings.get(k)]
        if len(active) > 1:
            for k in active[1:]:
                _settings[k] = False


def _save() -> None:
    """Persist current settings to disk (best-effort)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(_settings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def get(key: str) -> bool:
    return _settings.get(key, False)


def set(key: str, value: bool) -> None:
    _settings[key] = value
    _save()


def toggle(key: str) -> bool:
    _settings[key] = not _settings.get(key, False)
    _save()
    return _settings[key]


def toggle_radio(key: str) -> bool:
    """Toggle *key* as a radio button within its group."""
    group_name = _KEY_TO_GROUP.get(key)
    if group_name is None:
        return toggle(key)

    group_keys = RADIO_GROUPS[group_name]
    was_on = _settings.get(key, False)

    for k in group_keys:
        _settings[k] = False

    if not was_on:
        _settings[key] = True

    _save()
    return _settings[key]


def is_radio_key(key: str) -> bool:
    """Return True if *key* belongs to a radio group."""
    return key in _KEY_TO_GROUP


def any_auto_save() -> bool:
    return any(_settings[k] for k in _AUTO_SAVE_KEYS if k != "auto_save_off")


def get_active_font_name() -> str | None:
    """Return the display name of the currently selected font, or None."""
    for fk in _font_keys:
        if _settings.get(fk):
            return _KEY_TO_FONT_NAME.get(fk)
    return None


def get_active_font_key() -> str | None:
    """Return the settings key of the currently selected font, or None."""
    for fk in _font_keys:
        if _settings.get(fk):
            return fk
    return None


def get_active_theme_name() -> str | None:
    """Return the display name of the currently selected theme, or None."""
    for tk in _theme_keys:
        if _settings.get(tk):
            return _KEY_TO_THEME_NAME.get(tk)
    return None


def get_active_theme_key() -> str | None:
    """Return the settings key of the currently selected theme, or None."""
    for tk in _theme_keys:
        if _settings.get(tk):
            return tk
    return None


# Load on import so the module is ready immediately.
_load()
