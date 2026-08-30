"""Local auto-suggestion engine (VS Code-style popup), stdlib only.

Candidate sources, in order of priority:

1. Language keywords (from ``schema.language_keywords``).
2. Identifiers already present in the open document, ranked by how often
   they appear (and how close they are to the current cursor line).

The popup triggers automatically while typing an identifier and accepts
with Tab/Enter.  Pure logic here — rendering and key wiring live in ``tui``.
"""

from __future__ import annotations

import re
from collections import Counter

from .languages import schema

_WORD_CHARS = re.compile(r"[A-Za-z0-9_]+")
IDENTIFIER_RE = re.compile(r"[^\W\d]\w*")  # starts with a letter or underscore

DOC_SCAN_LIMIT = 2000  # max lines scanned for document-identifier suggestions
MAX_CANDIDATES = 10


def word_at(line: str, col: int) -> tuple[int, str]:
    """Return ``(start_col, prefix)`` of the identifier ending at *col*.

    ``col`` is the cursor position (the column right after the last typed
    char).  Returns ``(col, "")`` when the cursor is not inside/after an
    identifier character.
    """
    if col <= 0:
        return (col, "")
    matches = list(_WORD_CHARS.finditer(line[:col]))
    if not matches:
        return (col, "")
    last = matches[-1]
    if last.end() != col:
        return (col, "")
    return (last.start(), last.group())


def identifier_words(lines: list[str], limit: int = DOC_SCAN_LIMIT) -> Counter:
    """Collect identifiers from the first *limit* lines into a ``Counter``."""
    counts: Counter = Counter()
    for line in lines[:limit]:
        for m in IDENTIFIER_RE.finditer(line):
            counts[m.group()] += 1
    return counts


def candidates(
    language: str,
    doc_words: Counter,
    prefix: str,
    max_items: int = MAX_CANDIDATES,
) -> list[str]:
    """Return ranked suggestion strings matching *prefix* (case-insensitive)."""
    if not prefix:
        return []
    p = prefix.lower()
    kw = [k for k in schema.language_keywords(language)
          if k.lower().startswith(p)]
    if hasattr(doc_words, "most_common"):
        ordered = doc_words.most_common()
    else:
        ordered = sorted(doc_words.items(),
                         key=lambda kv: (-kv[1], kv[0]))
    words = [w for w, _ in ordered
             if w.lower().startswith(p) and w not in kw]
    return (kw + words)[:max_items]


class Suggestor:
    """Stateful popup: query, candidate list, live selection index."""

    def __init__(self, max_items: int = MAX_CANDIDATES) -> None:
        self.query = ""
        self.candidates: list[str] = []
        self.selected = 0
        self.visible = False
        self.max_items = max_items

    def open(self, language: str, doc_words: Counter, prefix: str) -> None:
        self.query = prefix
        self.candidates = candidates(language, doc_words, prefix, self.max_items)
        self.selected = 0
        self.visible = bool(self.candidates)

    def update(self, language: str, doc_words: Counter, prefix: str) -> None:
        self.open(language, doc_words, prefix)

    def close(self) -> None:
        self.visible = False
        self.candidates = []
        self.selected = 0

    def move(self, dy: int) -> None:
        if not self.candidates:
            return
        self.selected = (self.selected + dy) % len(self.candidates)

    def selected_text(self) -> str:
        if 0 <= self.selected < len(self.candidates):
            return self.candidates[self.selected]
        return ""

    def accept_suffix(self) -> str:
        """Return the text to insert for the selected candidate, or ''."""
        chosen = self.selected_text()
        if not chosen:
            return ""
        q = self.query
        if chosen.lower().startswith(q.lower()) and len(chosen) > len(q):
            return chosen[len(q):]
        if chosen.lower() == q.lower():
            self.close()
            return ""
        return chosen