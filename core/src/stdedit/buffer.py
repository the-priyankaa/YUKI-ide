"""
buffer.py — line-based text buffer with cursor, scrolling, undo/redo,
selection, clipboard, auto-indent, and tab/space conversion.

stdlib-only. No dependency on curses/TUI — this module is UI-agnostic
so it can be unit tested and driven by any front end (see tests/).
"""

from __future__ import annotations

import codecs
import os
import re
from typing import List, Optional, Tuple

from .storage.compact import CompactLines
from .storage.mapped import MappedLines
from .undo import UndoManager
from .clipboard import sys_copy, sys_paste
from .imageviewer import detect_format_path

DEFAULT_LARGE_FILE_BYTES = 8 * 1024 * 1024
BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSING_TO_OPENING = {v: k for k, v in BRACKET_PAIRS.items()}


_COALESCE_ACTIONS = {"insert_char", "backspace_char", "delete_char"}


class Buffer:
    def __init__(
        self,
        filename: Optional[str] = None,
        tab_size: int = 4,
        use_spaces: bool = True,
        large_file_threshold: int = DEFAULT_LARGE_FILE_BYTES,
    ) -> None:
        self.filename: Optional[str] = None
        self._lines: List[str] | CompactLines | MappedLines = [""]
        self.cursor_x = 0
        self.cursor_y = 0
        self.scroll_x = 0
        self.scroll_y = 0
        self.tab_size = tab_size
        self.use_spaces = use_spaces
        self._increase_re: Optional[re.Pattern] = None
        self._decrease_re: Optional[re.Pattern] = None
        self.modified = False
        self.large_file_threshold = max(0, large_file_threshold)
        self.large_file_mode = False
        self._content_chars = 0
        self.encoding = "utf-8"
        self.newline = "\n"
        self.image_format: Optional[str] = None
        self.image_path: Optional[str] = None
        self.load_error: Optional[str] = None

        self.undo_mgr = UndoManager()
        self._last_action: Optional[str] = None
        self.selection_anchor: Optional[Tuple[int, int]] = None
        self.clipboard: str = ""

        if filename:
            self.load(filename)

    @property
    def lines(self):
        return self._lines

    @lines.setter
    def lines(self, value):
        # Keep the fast list representation for ordinary documents.  Large
        # documents use CompactLines so RAM is not dominated by one Python
        # string object per source line.
        if (
            isinstance(value, list)
            and self.large_file_mode
            and self.encoding in {"utf-8", "utf-8-sig", "latin-1"}
            and sum(len(x) for x in value) >= self.large_file_threshold
        ):
            enc = "utf-8" if self.encoding == "utf-8-sig" else self.encoding
            self._lines = CompactLines(value, enc)
        else:
            self._lines = value

    def _materialize_mapped(self):
        if not isinstance(self._lines, MappedLines):
            return self._lines
        mapped = self._lines
        lines = list(mapped)
        enc = "utf-8" if self.encoding == "utf-8-sig" else self.encoding
        mapped.close()
        self._lines = CompactLines(lines, enc)
        return self._lines

    def _set_inert(self, message: str) -> None:
        """Leave the buffer non-editable with a single placeholder line.

        Used for files that cannot be safely opened as text (unreadable
        paths, embedded-NUL binary files).  ``load_error`` records a message
        the TUI surfaces instead of crashing on a null-character draw.
        """
        self.filename = self.filename
        self.encoding = "latin-1"
        self.newline = "\n"
        self._lines = ["  " + message]
        self._content_chars = len(self._lines[0])
        self.cursor_x = 0
        self.cursor_y = 0
        self.selection_anchor = None
        self.modified = False
        self.undo_mgr = UndoManager()
        self._last_action = None
        self.large_file_mode = False
        self.image_format = None
        self.image_path = None
        self.load_error = message

    # ------------------------------------------------------------------ #
    # File I/O
    # ------------------------------------------------------------------ #
    @staticmethod
    def _detect_streamed_encoding(path: str):
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(4)
        if head.startswith(codecs.BOM_UTF8):
            encoding, bom_len = "utf-8-sig", len(codecs.BOM_UTF8)
        elif head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE):
            encoding, bom_len = "utf-16", 2
        elif head.startswith(codecs.BOM_UTF32_LE) or head.startswith(codecs.BOM_UTF32_BE):
            encoding, bom_len = "utf-32", 4
        else:
            encoding, bom_len = "utf-8", 0

        newline = "\n"
        decoder = None
        if encoding in {"utf-8", "utf-8-sig"}:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        prev = None
        valid = True
        with open(path, "rb") as f:
            if bom_len:
                f.seek(bom_len)
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                if b"\r\n" in chunk or (prev == 13 and chunk.startswith(b"\n")):
                    newline = "\r\n"
                prev = chunk[-1] if chunk else prev
                if decoder is not None:
                    try:
                        decoder.decode(chunk, final=False)
                    except UnicodeDecodeError:
                        valid = False
                        break
            if decoder is not None and valid:
                try:
                    decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    valid = False
        if not valid and bom_len == 0:
            encoding = "latin-1"
        return encoding, bom_len, newline, size

    def load(self, path: str) -> None:
        self.image_format = None
        self.image_path = None
        self.load_error = None

        fmt = detect_format_path(path)
        if fmt is not None:
            # Binary image file: keep the buffer inert (single placeholder
            # line) and let the TUI switch it into the integrated viewer.
            self.filename = path
            self.encoding = "latin-1"
            self.newline = "\n"
            self._lines = ["  <binary image — integrated viewer active (q: raw view  Ctrl-\\: reopen viewer)>"]
            self._content_chars = len(self._lines[0])
            self.cursor_x = 0
            self.cursor_y = 0
            self.selection_anchor = None
            self.modified = False
            self.undo_mgr = UndoManager()
            self._last_action = None
            self.large_file_mode = False
            self.image_format = fmt
            self.image_path = path
            return

        try:
            file_size = os.path.getsize(path)
            with open(path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            raise  # let callers treat a missing file as an empty/new file
        except (OSError, ValueError) as exc:
            # Unreadable / directory path must never crash the TUI: degrade
            # to an inert buffer and surface the message as status.
            self._set_inert(f"Cannot read file: {exc}")
            self.filename = path
            return

        is_large = bool(self.large_file_threshold and file_size >= self.large_file_threshold)

        if is_large:
            encoding, bom_len, newline, _ = self._detect_streamed_encoding(path)
            self.encoding = encoding
            self.newline = newline
        else:
            encoding = "utf-8"
            bom_len = 0
            # Decode the *whole* buffer with the BOM-aware codec so a UTF-16/32
            # BOM document decodes correctly even when the byte count is uneven;
            # the codec itself strips the BOM and starts from the anchor endian.
            if raw.startswith(codecs.BOM_UTF8):
                encoding = "utf-8-sig"
                bom_len = len(codecs.BOM_UTF8)
            elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                encoding = "utf-16"
                bom_len = 0
            elif raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                encoding = "utf-32"
                bom_len = 0
            try:
                raw[bom_len:].decode(encoding)
            except UnicodeDecodeError:
                try:
                    raw.decode("utf-8")
                    encoding = "utf-8"
                    bom_len = 0
                except UnicodeDecodeError:
                    # Pure latin-1 text: no NULs here (checked above), so this
                    # keeps every byte but never crashes the renderer.
                    raw.decode("latin-1")
                    encoding = "latin-1"
                    bom_len = 0
            self.encoding = encoding
            self.newline = "\r\n" if b"\r\n" in raw else "\n"

        self.large_file_mode = is_large

        if is_large and encoding in {"utf-8", "utf-8-sig", "latin-1"}:
            # Start in a disk-backed representation. This keeps opening/
            # browsing a 100+ MB file from duplicating the entire document in
            # Python memory. The first edit materializes to CompactLines.
            self._lines = MappedLines(path, "utf-8" if encoding == "utf-8-sig" else encoding, self._materialize_mapped)
            self._content_chars = file_size
        else:
            text = raw[bom_len:].decode(encoding)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if "\x00" in text:
                # Embedded NUL in the decoded text means a non-image binary
                # file (latin-1 fallback preserved raw NUL bytes).  Keep the
                # buffer inert rather than letting control bytes reach the
                # curses renderer; UTF-16/32 documents decode without NULs.
                self._set_inert("Binary/non-text file — cannot be opened as text")
                self.large_file_mode = False
                self.filename = path
                return
            self._lines = text.split("\n") or [""]
            self._content_chars = sum(len(line) for line in self._lines)

        self.filename = path
        self.cursor_x = 0
        self.cursor_y = 0
        self.selection_anchor = None
        self.modified = False
        self.undo_mgr = UndoManager()
        self._last_action = None

    def save(self, path: Optional[str] = None) -> None:
        target = path or self.filename
        if not target:
            raise ValueError("No filename to save to")
        if isinstance(self._lines, MappedLines):
            enc = "utf-8" if self.encoding == "utf-8-sig" else self.encoding
            if target == self.filename and not self.modified:
                pass
            else:
                self._write_encoded(target, enc)
        elif isinstance(self._lines, CompactLines):
            enc = "utf-8" if self.encoding == "utf-8-sig" else self.encoding
            self._write_encoded(target, enc)
        else:
            text = self.newline.join(self._lines)
            with open(target, "w", encoding=self.encoding, newline="") as f:
                f.write(text)
        self.filename = target
        self.modified = False

    def _write_encoded(self, target: str, enc: str) -> None:
        newline = self.newline.encode(enc)
        with open(target, "wb") as f:
            if self.encoding == "utf-8-sig":
                f.write(codecs.BOM_UTF8)
            for i, line in enumerate(self._lines):
                f.write(line.encode(enc))
                if i + 1 < len(self._lines):
                    f.write(newline)

    # ------------------------------------------------------------------ #
    # Basic accessors / cursor movement
    # ------------------------------------------------------------------ #
    @property
    def current_line(self) -> str:
        return self.lines[self.cursor_y]

    @property
    def content_size_bytes(self) -> int:
        """Cheap logical content-size estimate used for large-file safety."""
        if isinstance(self._lines, CompactLines):
            return len(self._lines._data)
        if isinstance(self._lines, MappedLines):
            return os.path.getsize(self.filename) if self.filename else self._content_chars
        return self._content_chars + max(0, len(self.lines) - 1)

    def _set_content_chars(self, value: int) -> None:
        self._content_chars = max(0, value)
        if (not self.large_file_mode and self.large_file_threshold and self.content_size_bytes >= self.large_file_threshold):
            self.large_file_mode = True
            self.undo_mgr = UndoManager()

    def _refresh_content_chars(self) -> None:
        if isinstance(self._lines, CompactLines):
            self._content_chars = sum(len(line) for line in self._lines)
        else:
            self._set_content_chars(sum(len(line) for line in self.lines))

    def line_count(self) -> int:
        return len(self.lines)

    def configure_for_language(self, language: str) -> None:
        """Set indent size and auto-indent patterns from language config.

        ``increase_re`` causes insert_newline to add one extra indent level
        when the line before the cursor matches it (e.g. ``:``, ``{``).
        ``decrease_re`` causes insert_newline to *remove* one indent level
        when the text after the cursor matches it (e.g. ``}``).
        """
        from .languages.schema import get_indent_spec
        spec = get_indent_spec(language)
        self.tab_size = spec.get("size", 4)
        inc = spec.get("increase")
        dec = spec.get("decrease")
        self._increase_re = re.compile(inc) if inc else None
        self._decrease_re = re.compile(dec) if dec else None

    def clamp_cursor(self) -> None:
        self.cursor_y = max(0, min(self.cursor_y, len(self.lines) - 1))
        self.cursor_x = max(0, min(self.cursor_x, len(self.lines[self.cursor_y])))

    def move_cursor(self, dx: int = 0, dy: int = 0, extend_selection: bool = False) -> None:
        self._selection_guard(extend_selection)

        if dy != 0:
            self.cursor_y = max(0, min(self.cursor_y + dy, len(self.lines) - 1))
            self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))

        if dx != 0:
            self.cursor_x += dx
            if self.cursor_x < 0:
                if self.cursor_y > 0:
                    self.cursor_y -= 1
                    self.cursor_x = len(self.lines[self.cursor_y])
                else:
                    self.cursor_x = 0
            elif self.cursor_x > len(self.lines[self.cursor_y]):
                if self.cursor_y < len(self.lines) - 1:
                    self.cursor_y += 1
                    self.cursor_x = 0
                else:
                    self.cursor_x = len(self.lines[self.cursor_y])

    def move_to(self, x: int, y: int, extend_selection: bool = False) -> None:
        self._selection_guard(extend_selection)
        self.cursor_y = max(0, min(y, len(self.lines) - 1))
        self.cursor_x = max(0, min(x, len(self.lines[self.cursor_y])))

    def find_next(self, query: str) -> Optional[Tuple[int, int, int]]:
        """Find next occurrence of *query* after cursor (case-insensitive).

        Wraps around from the end of the buffer back to the top.
        Moves cursor to the match start and returns ``(line, start, end)``
        or ``None`` when nothing matches.
        """
        if not query:
            return None
        q = query.lower()
        line_count = len(self.lines)

        # Search from cursor_x + 1 on the current line.
        line = self.lines[self.cursor_y]
        start = line.lower().find(q, self.cursor_x + 1)
        if start >= 0:
            self.move_to(start, self.cursor_y)
            return (self.cursor_y, start, start + len(query))

        # Search subsequent lines.
        for y in range(self.cursor_y + 1, line_count):
            line = self.lines[y]
            start = line.lower().find(q)
            if start >= 0:
                self.move_to(start, y)
                return (y, start, start + len(query))

        # Wrap: search from the beginning up to the cursor position.
        for y in range(0, self.cursor_y + 1):
            line = self.lines[y]
            end = self.cursor_x if y == self.cursor_y else len(line)
            start = line.lower().find(q, 0, end)
            if start >= 0:
                self.move_to(start, y)
                return (y, start, start + len(query))

        return None

    def update_scroll(self, viewport_height: int, viewport_width: int) -> None:
        """Keep cursor within the visible viewport. Called by the TUI each frame."""
        if self.cursor_y < self.scroll_y:
            self.scroll_y = self.cursor_y
        elif self.cursor_y >= self.scroll_y + viewport_height:
            self.scroll_y = self.cursor_y - viewport_height + 1

        if self.cursor_x < self.scroll_x:
            self.scroll_x = self.cursor_x
        elif self.cursor_x >= self.scroll_x + viewport_width:
            self.scroll_x = self.cursor_x - viewport_width + 1

    def _selection_guard(self, extend_selection: bool) -> None:
        if extend_selection:
            if self.selection_anchor is None:
                self.selection_anchor = (self.cursor_y, self.cursor_x)
        else:
            self.selection_anchor = None

    # ------------------------------------------------------------------ #
    # Undo/redo plumbing
    # ------------------------------------------------------------------ #
    def _checkpoint_if_needed(self, action: str) -> None:
        # Large documents skip snapshot history by default. This avoids the
        # O(number-of-lines) tuple allocation on every edit and prevents the
        # undo system from retaining large document states.
        if not self.large_file_mode and not (action in _COALESCE_ACTIONS and self._last_action == action):
            self.undo_mgr.checkpoint(self.lines, self.cursor_x, self.cursor_y)
        self._last_action = action

    def _restore_snapshot(self, snap) -> bool:
        if snap is None:
            return False
        self.lines = list(snap.lines)
        self.cursor_x, self.cursor_y = snap.cursor_x, snap.cursor_y
        self.selection_anchor = None
        self._last_action = None
        self.clamp_cursor()
        self._refresh_content_chars()
        self.modified = True
        return True

    def undo(self) -> bool:
        return self._restore_snapshot(
            self.undo_mgr.undo(self.lines, self.cursor_x, self.cursor_y)
        )

    def redo(self) -> bool:
        return self._restore_snapshot(
            self.undo_mgr.redo(self.lines, self.cursor_x, self.cursor_y)
        )

    # ------------------------------------------------------------------ #
    # Editing
    # ------------------------------------------------------------------ #
    def insert_char(self, ch: str) -> None:
        if self.has_selection():
            self.delete_selection()
        self._checkpoint_if_needed("insert_char")
        line = self.lines[self.cursor_y]
        self.lines[self.cursor_y] = line[: self.cursor_x] + ch + line[self.cursor_x :]
        self.cursor_x += 1
        self._set_content_chars(self._content_chars + len(ch))
        self.modified = True

    def smart_dedent_on_char(self, ch: str) -> bool:
        """Dedent when a block-closer is typed as the first non-ws char.

        If ``ch`` matches the language's ``decrease`` regex and the line
        contains only whitespace before the cursor, remove one indent
        level so the closer aligns with its matching opener.

        Returns True if a dedent was applied (the caller should know
        the line content has been mutated by this method).
        """
        if not self._decrease_re:
            return False
        if not re.match(self._decrease_re, ch):
            return False
        line = self.lines[self.cursor_y]
        before_cursor = line[: self.cursor_x]
        if before_cursor.strip():
            return False  # there is non-whitespace before cursor — don't touch
        if not before_cursor:
            return False  # nothing to dedent
        # Remove one indent level from the leading whitespace.
        if self.use_spaces:
            cut = self.tab_size
            if len(before_cursor) >= cut:
                new_before = before_cursor[cut:]
            else:
                new_before = ""
        else:
            new_before = before_cursor[:-1] if before_cursor.endswith("\t") else ""
        rest = line[self.cursor_x:]
        self.lines[self.cursor_y] = new_before + ch + rest
        self.cursor_x = len(new_before) + 1
        self._refresh_content_chars()
        self.modified = True
        return True

    def insert_newline(self) -> None:
        """Split the current line and smart-indent the new line.

        Copies the current line's leading whitespace, then applies
        language-aware indentation rules:

        - *increase*: if the line before the cursor matches the language's
          ``increase`` regex (e.g. ``:``, ``{``), one extra indent level is
          added.
        - *decrease*: if the text after the cursor matches the language's
          ``decrease`` regex (e.g. ``}``, ``]``), one indent level is
          removed from the new line so the closer sits at the right depth.
        """
        if self.has_selection():
            self.delete_selection()
        self._checkpoint_if_needed("insert_newline")
        line = self.lines[self.cursor_y]
        before, after = line[: self.cursor_x], line[self.cursor_x :]
        indent = re.match(r"[ \t]*", before).group(0)

        # Increase indent when the line introduces a block.
        if self._increase_re and re.search(self._increase_re, before.rstrip()):
            indent += " " * self.tab_size if self.use_spaces else "\t"
        elif not self._increase_re and before.rstrip().endswith(":"):
            # Safe fallback: colon-based indent for unconfigured buffers.
            indent += " " * self.tab_size if self.use_spaces else "\t"
        # Decrease indent when the next part starts with a block closer.
        if (self._decrease_re and after.lstrip()
                and re.match(self._decrease_re, after.lstrip())):
            if self.use_spaces:
                cut = self.tab_size
                indent = indent[cut:] if len(indent) >= cut else ""
            else:
                indent = indent[1:] if indent.startswith("\t") else indent

        self.lines[self.cursor_y] = before
        self.lines.insert(self.cursor_y + 1, indent + after)
        self.cursor_y += 1
        self.cursor_x = len(indent)
        self._set_content_chars(self._content_chars + len(indent) + 1)
        self.modified = True

    def backspace(self) -> None:
        if self.has_selection():
            self.delete_selection()
            return
        self._checkpoint_if_needed("backspace_char")
        if self.cursor_x > 0:
            line = self.lines[self.cursor_y]
            self.lines[self.cursor_y] = line[: self.cursor_x - 1] + line[self.cursor_x :]
            self.cursor_x -= 1
            self._set_content_chars(self._content_chars - 1)
            self.modified = True
        elif self.cursor_y > 0:
            prev_len = len(self.lines[self.cursor_y - 1])
            self.lines[self.cursor_y - 1] += self.lines[self.cursor_y]
            del self.lines[self.cursor_y]
            self.cursor_y -= 1
            self.cursor_x = prev_len
            self._set_content_chars(self._content_chars - 1)
            self.modified = True

    def delete_char(self) -> None:
        """Forward delete (the 'Delete' key, not backspace)."""
        if self.has_selection():
            self.delete_selection()
            return
        self._checkpoint_if_needed("delete_char")
        line = self.lines[self.cursor_y]
        if self.cursor_x < len(line):
            self.lines[self.cursor_y] = line[: self.cursor_x] + line[self.cursor_x + 1 :]
            self._set_content_chars(self._content_chars - 1)
            self.modified = True
        elif self.cursor_y < len(self.lines) - 1:
            self.lines[self.cursor_y] += self.lines[self.cursor_y + 1]
            del self.lines[self.cursor_y + 1]
            self._set_content_chars(self._content_chars - 1)
            self.modified = True

    def insert_tab(self) -> None:
        if self.has_selection():
            self.indent_selection()
            return
        self._checkpoint_if_needed("insert_char")
        if self.use_spaces:
            width = self.tab_size - (self.cursor_x % self.tab_size)
            text = " " * width
        else:
            text = "\t"
        line = self.lines[self.cursor_y]
        self.lines[self.cursor_y] = line[: self.cursor_x] + text + line[self.cursor_x :]
        self.cursor_x += len(text)
        self._set_content_chars(self._content_chars + len(text))
        self.modified = True

    # ------------------------------------------------------------------ #
    # Brackets
    # ------------------------------------------------------------------ #
    def matching_bracket(self) -> Optional[Tuple[int, int]]:
        """Return the position of the bracket matching the cursor.

        The cursor may sit immediately before a bracket or immediately after
        an opening/closing bracket. The scan is intentionally lightweight and
        ignores brackets inside quoted strings/comments only insofar as this
        core does not own a parser; it is designed for common editor use.
        """
        line = self.current_line
        candidates = []
        if self.cursor_x < len(line) and line[self.cursor_x] in BRACKET_PAIRS:
            candidates.append((self.cursor_y, self.cursor_x, line[self.cursor_x]))
        if self.cursor_x > 0 and line[self.cursor_x - 1] in BRACKET_PAIRS:
            candidates.insert(0, (self.cursor_y, self.cursor_x - 1, line[self.cursor_x - 1]))
        if self.cursor_x < len(line) and line[self.cursor_x] in CLOSING_TO_OPENING:
            candidates.insert(0, (self.cursor_y, self.cursor_x, line[self.cursor_x]))
        if self.cursor_x > 0 and line[self.cursor_x - 1] in CLOSING_TO_OPENING:
            candidates.append((self.cursor_y, self.cursor_x - 1, line[self.cursor_x - 1]))
        for y, x, ch in candidates:
            target = BRACKET_PAIRS.get(ch) or CLOSING_TO_OPENING.get(ch)
            direction = 1 if ch in BRACKET_PAIRS else -1
            depth = 1
            yy, xx = y, x
            while 0 <= yy < len(self.lines):
                text = self.lines[yy]
                start = xx + direction if yy == y else (0 if direction > 0 else len(text) - 1)
                indexes = range(start, len(text), 1) if direction > 0 else range(start, -1, -1)
                for i in indexes:
                    c = text[i]
                    if c == ch:
                        depth += 1
                    elif c == target:
                        depth -= 1
                        if depth == 0:
                            return yy, i
                yy += direction
        return None

    def auto_close_bracket(self, opener: str) -> bool:
        """Insert a matching pair and place the cursor between it."""
        closer = BRACKET_PAIRS.get(opener)
        if closer is None or self.has_selection():
            return False
        self._checkpoint_if_needed("insert_char")
        line = self.current_line
        self.lines[self.cursor_y] = line[:self.cursor_x] + opener + closer + line[self.cursor_x:]
        self.cursor_x += 1
        self._set_content_chars(self._content_chars + 2)
        self.modified = True
        return True

    def skip_closer(self, ch: str) -> bool:
        """Move over an existing auto-closed closer instead of duplicating it."""
        if self.cursor_x < len(self.current_line) and self.current_line[self.cursor_x] == ch:
            self.cursor_x += 1
            return True
        return False

    # ------------------------------------------------------------------ #
    # Selection
    # ------------------------------------------------------------------ #
    def has_selection(self) -> bool:
        return self.selection_anchor is not None and self.selection_anchor != (
            self.cursor_y,
            self.cursor_x,
        )

    def clear_selection(self) -> None:
        self.selection_anchor = None

    def select_all(self) -> None:
        self.selection_anchor = (0, 0)
        last = len(self.lines) - 1
        if self.lines[last]:
            self.cursor_y = last
            self.cursor_x = len(self.lines[last])
        elif last > 0:
            self.cursor_y = last - 1
            self.cursor_x = len(self.lines[last - 1])
        else:
            self.cursor_y = 0
            self.cursor_x = 0

    def select_word_at(self, y: int, x: int) -> None:
        """Select the word at position (y, x)."""
        if y < 0 or y >= len(self.lines):
            return
        line = self.lines[y]
        if not line or x < 0 or x >= len(line):
            return
        ch = line[x]
        if ch.isalnum() or ch == '_':
            is_word = True
        else:
            is_word = False
        # Expand left
        start = x
        while start > 0:
            prev = line[start - 1]
            if is_word:
                if not (prev.isalnum() or prev == '_'):
                    break
            else:
                if prev.isalnum() or prev == '_':
                    break
            start -= 1
        # Expand right
        end = x + 1
        while end < len(line):
            nxt = line[end]
            if is_word:
                if not (nxt.isalnum() or nxt == '_'):
                    break
            else:
                if nxt.isalnum() or nxt == '_':
                    break
            end += 1
        self.selection_anchor = (y, start)
        self.cursor_y = y
        self.cursor_x = end

    def select_line_at(self, y: int) -> None:
        """Select the entire line at position y."""
        if y < 0 or y >= len(self.lines):
            return
        self.selection_anchor = (y, 0)
        self.cursor_y = y
        self.cursor_x = len(self.lines[y])

    def _normalized_selection(self) -> Optional[Tuple[int, int, int, int]]:
        if not self.has_selection():
            return None
        ay, ax = self.selection_anchor
        by, bx = self.cursor_y, self.cursor_x
        return (ay, ax, by, bx) if (ay, ax) <= (by, bx) else (by, bx, ay, ax)

    def selected_text(self) -> str:
        sel = self._normalized_selection()
        if not sel:
            return ""
        sy, sx, ey, ex = sel
        if sy == ey:
            return self.lines[sy][sx:ex]
        parts = [self.lines[sy][sx:]]
        parts.extend(self.lines[sy + 1 : ey])
        parts.append(self.lines[ey][:ex])
        return "\n".join(parts)

    def delete_selection(self) -> None:
        sel = self._normalized_selection()
        if not sel:
            return
        self._checkpoint_if_needed("delete_selection")
        sy, sx, ey, ex = sel
        if sy == ey:
            line = self.lines[sy]
            self.lines[sy] = line[:sx] + line[ex:]
            self._set_content_chars(self._content_chars - (ex - sx))
        else:
            head, tail = self.lines[sy][:sx], self.lines[ey][ex:]
            removed_chars = (len(self.lines[sy]) - sx) + ex
            removed_lines = ey - sy
            self.lines[sy] = head + tail
            del self.lines[sy + 1 : ey + 1]
            self._set_content_chars(self._content_chars - removed_chars)
            self._set_content_chars(self._content_chars - removed_lines)
        self.cursor_y, self.cursor_x = sy, sx
        self.selection_anchor = None
        self.modified = True

    def indent_selection(self) -> None:
        sel = self._normalized_selection()
        pad = " " * self.tab_size if self.use_spaces else "\t"
        rng = range(sel[0], sel[2] + 1) if sel else [self.cursor_y]
        self._checkpoint_if_needed("indent_selection")
        for i in rng:
            if self.lines[i]:
                self.lines[i] = pad + self.lines[i]
        self._refresh_content_chars()
        self.modified = True

    # ------------------------------------------------------------------ #
    # Clipboard (internal — stdlib only, no OS clipboard dependency)
    # ------------------------------------------------------------------ #
    def copy(self) -> str:
        text = self.selected_text()
        if text:
            self.clipboard = text
            sys_copy(text)
        return self.clipboard

    def cut(self) -> str:
        text = self.selected_text()
        if text:
            self.clipboard = text
            sys_copy(text)
            self.delete_selection()
        return self.clipboard

    def paste(self, text: Optional[str] = None) -> None:
        if text is None:
            # Try system clipboard first, fall back to internal.
            sys_text = sys_paste()
            text = sys_text if sys_text else self.clipboard
        if not text:
            return
        if self.has_selection():
            self.delete_selection()
        self._checkpoint_if_needed("paste")
        parts = text.split("\n")
        line = self.lines[self.cursor_y]
        before, after = line[: self.cursor_x], line[self.cursor_x :]

        if len(parts) == 1:
            self.lines[self.cursor_y] = before + parts[0] + after
            self.cursor_x += len(parts[0])
        else:
            # When pasting into a blank/indent-only line, rebase the pasted
            # block onto that line's indentation. This gives the expected
            # editor behavior for pasting Python code into a block while
            # preserving the relative indentation inside the pasted block.
            # If there is already code before the cursor, preserve the paste
            # verbatim rather than unexpectedly rewriting it.
            if not before.strip():
                current_indent = before
                nonempty = next((p for p in parts if p.strip()), "")
                pasted_indent = re.match(r"[ \t]*", nonempty).group(0)
                base_width = len(pasted_indent.expandtabs(self.tab_size))
                current_width = len(current_indent.expandtabs(self.tab_size))
                adjusted = []
                for p in parts:
                    leading = re.match(r"[ \t]*", p).group(0)
                    width = len(leading.expandtabs(self.tab_size))
                    relative = max(0, width - base_width)
                    if self.use_spaces:
                        new_indent = " " * (current_width + relative)
                    else:
                        # Keep tabs for whole indentation levels and spaces
                        # for any remainder.
                        tabs, spaces = divmod(current_width + relative, self.tab_size)
                        new_indent = "\t" * tabs + " " * spaces
                    adjusted.append(new_indent + p[len(leading):])
                parts = adjusted

            # The rebased first pasted line already contains the current
            # indentation, so do not prepend `before` a second time.
            first_prefix = "" if not before.strip() else before
            self.lines[self.cursor_y] = first_prefix + parts[0]
            middle = parts[1:-1]
            last = parts[-1] + after
            insert_at = self.cursor_y + 1
            for i, p in enumerate(middle):
                self.lines.insert(insert_at + i, p)
            self.lines.insert(insert_at + len(middle), last)
            self.cursor_y = insert_at + len(middle)
            self.cursor_x = len(parts[-1])
        self._set_content_chars(self._content_chars + len(text))
        self.modified = True
