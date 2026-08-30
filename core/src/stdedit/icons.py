"""
icons.py -- optional Nerd Font glyph mapping. stdlib only.

Glyphs live in terminal fonts, not in stdedit: a curses program cannot
set the terminal's font.  Icons therefore render correctly only when
the terminal uses a Nerd Font (recommended: MesloLGS NF); elsewhere
they appear as placeholder boxes and can be turned off with
STDEDIT_ICONS=0.  Codepoints target Nerd Fonts v3 (stable seti/dev/
fontawesome planes).
"""

from __future__ import annotations

import os

# Language name (as reported by languages.schema.detect_language) -> glyph.
LANG_ICONS = {
    "python": "\uE73C",       # nf-dev-python
    "javascript": "\uE74E",   # nf-dev-javascript
    "typescript": "\uE628",   # nf-seti-typescript
    "html": "\uE736",         # nf-dev-html5
    "css": "\uE749",          # nf-dev-css3
    "c": "\uE61E",            # nf-seti-c
    "cpp": "\uE61D",          # nf-seti-cpp
    "java": "\uE738",         # nf-dev-java
    "rust": "\uE7A8",         # nf-dev-rust
    "go": "\uE626",           # nf-seti-go
    "json": "\uE60B",         # nf-seti-json
    "yaml": "\uE615",         # nf-seti-yml
    "markdown": "\uE609",     # nf-seti-markdown
    "shell": "\uE795",        # nf-dev-terminal
    "sql": "\uE706",          # nf-dev-database
    "xml": "\uF121",          # fa-code
    "plaintext": "\uF15C",    # fa-file-text-o
}

# Extension-based extras that have no dedicated language entry.
EXT_ICONS = {
    ".lock": "\uF023",                          # fa-lock
    ".toml": "\uF013",                          # fa-cog (config)
    ".ini": "\uF013",
    ".cfg": "\uF013",
    ".png": "\uF1C5",                           # fa-file-image-o
    ".jpg": "\uF1C5",
    ".jpeg": "\uF1C5",
    ".gif": "\uF1C5",
    ".svg": "\uF1C5",
    ".ico": "\uF1C5",
}

DEFAULT_ICON = "\uF15B"  # fa-file


def enabled_from_env(environ=None) -> bool:
    """Icons are ON unless STDEDIT_ICONS=0."""
    return (os.environ if environ is None else environ).get(
        "STDEDIT_ICONS", "") != "0"


def icon_for_file(filename, enabled: bool) -> str:
    """Icon for a filename by extension; "" when icons are disabled."""
    if not enabled:
        return ""
    lower = (filename or "").lower()
    for ext, glyph in EXT_ICONS.items():
        if lower.endswith(ext):
            return glyph
    return DEFAULT_ICON


def icon_for_language(language_label, enabled: bool) -> str:
    """Icon for a language name; "" when disabled or unknown."""
    if not enabled:
        return ""
    return LANG_ICONS.get((language_label or "").lower(), "")
