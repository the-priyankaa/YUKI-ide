"""Tiny cross-platform process-memory/performance helpers for stdedit.

No third-party dependencies. Sampling is intentionally explicit so the TUI can
update the meter at a low frequency instead of doing work on every keypress.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional


def rss_bytes() -> Optional[int]:
    """Return current resident set size in bytes, or None when unavailable.

    Linux reads /proc/self/statm.  macOS/BSD fall back to getrusage, whose
    ru_maxrss is reported in *bytes* there (KiB on Linux) — normalised so the
    dashboard meter reads the same everywhere.  Platforms without ``resource``
    (e.g. Windows) return None and the meter shows ``RAM --`` instead of
    crashing.
    """
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGESIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    try:
        import resource
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, OSError, AttributeError, ValueError):
        return None
    # ru_maxrss units: KiB on Linux/Cygwin, bytes on macOS/BSD.
    if sys.platform.startswith(("darwin", "freebsd", "openbsd", "netbsd",
                                "dragonfly")):
        return value
    return value * 1024


def format_bytes(value: Optional[int]) -> str:
    if value is None:
        return "RAM --"
    units = ("B", "KB", "MB", "GB")
    n = float(value)
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"RAM {n:.1f} {unit}"
        n /= 1024
    return "RAM --"


class PerfMeter:
    """Low-frequency RSS + frame timing sampler."""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self._next_sample = 0.0
        self.rss: Optional[int] = None
        self.frame_ms = 0.0

    def frame_start(self) -> float:
        return time.perf_counter()

    def frame_end(self, started: float) -> None:
        self.frame_ms = (time.perf_counter() - started) * 1000.0
        now = time.monotonic()
        if now >= self._next_sample:
            self.rss = rss_bytes()
            self._next_sample = now + self.interval

    def label(self) -> str:
        return f"{format_bytes(self.rss)}  {self.frame_ms:.1f} ms"
