"""Detect installed monospace fonts on the system.

Uses ``fc-list`` when available, falls back to a hardcoded list.
Font names are sanitized into valid settings keys (lowercase,
underscores, no special characters).
"""

from __future__ import annotations

import subprocess

_FALLBACK_FONTS = [
    "Hack",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Adwaita Mono",
]

_EXCLUDE = {"Icons", "Emoji", "SignWriting", "Material"}


def detect_monospace_fonts() -> list[str]:
    """Return installed monospace font family names, sorted and deduped."""
    try:
        result = subprocess.run(
            ["fc-list", ":spacing=mono", "family"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return list(_FALLBACK_FONTS)
        families = set()
        for line in result.stdout.splitlines():
            name = line.split(",")[0].strip()
            if name and not any(ex in name for ex in _EXCLUDE):
                families.add(name)
        if not families:
            return list(_FALLBACK_FONTS)
        return sorted(families)
    except (OSError, subprocess.TimeoutExpired):
        return list(_FALLBACK_FONTS)


def sanitize_font_key(name: str) -> str:
    """Convert a font family name to a valid settings key.

    ``"DejaVu Sans Mono"`` → ``"font_dejavu_sans_mono"``
    ``"Hack"``             → ``"font_hack"``
    """
    safe = name.lower().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c == "_")
    return f"font_{safe}"


def font_keys_and_labels() -> tuple[list[str], list[str]]:
    """Return (keys, labels) for detected monospace fonts.

    keys:   ``["font_hack", "font_dejavu_sans_mono", ...]``
    labels: ``["Hack", "DejaVu Sans Mono", ...]``
    """
    fonts = detect_monospace_fonts()
    keys = [sanitize_font_key(f) for f in fonts]
    return keys, fonts
