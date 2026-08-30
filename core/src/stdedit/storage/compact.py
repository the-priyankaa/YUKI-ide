"""Compact line storage for large UTF-8/Latin-1 documents.

Stores the document as one bytearray plus a compact array of line starts,
avoiding one Python string object per line.  It deliberately implements only
the list operations used by Buffer; decoded strings are materialized only for
the line(s) actually touched/rendered.
"""
from __future__ import annotations

from array import array
from typing import Iterator, Sequence, Union

LineIndex = Union[int, slice]


class CompactLines:
    __slots__ = ("_data", "_starts", "_encoding")

    def __init__(self, lines: Sequence[str], encoding: str = "utf-8") -> None:
        self._encoding = encoding
        self._data = bytearray()
        self._starts = array("I", [0])
        for i, line in enumerate(lines):
            if i:
                self._data.append(10)
                self._starts.append(len(self._data))
            self._data.extend(line.encode(encoding))
        # Empty document is represented by one line.
        if not lines:
            self._data.clear()
            self._starts = array("I", [0])

    def __len__(self) -> int:
        return len(self._starts)

    def _bounds(self, idx: int) -> tuple[int, int]:
        if idx < 0:
            idx += len(self)
        if idx < 0 or idx >= len(self):
            raise IndexError(idx)
        start = self._starts[idx]
        end = self._starts[idx + 1] - 1 if idx + 1 < len(self) else len(self._data)
        if end > start and self._data[end - 1] == 10:
            end -= 1
        return start, end

    def __getitem__(self, idx: LineIndex):
        if isinstance(idx, slice):
            return [self[i] for i in range(*idx.indices(len(self)))]
        start, end = self._bounds(idx)
        return bytes(self._data[start:end]).decode(self._encoding)

    def __setitem__(self, idx: int, value: str) -> None:
        start, end = self._bounds(idx)
        new = value.encode(self._encoding)
        self._data[start:end] = new
        delta = len(new) - (end - start)
        if delta:
            for j in range(idx + 1, len(self._starts)):
                self._starts[j] += delta

    def insert(self, idx: int, value: str) -> None:
        n = len(self)
        if idx < 0:
            idx = max(0, n + idx)
        idx = min(idx, n)
        encoded = value.encode(self._encoding)
        if idx == n:
            if n:
                self._data.append(10)
                self._starts.append(len(self._data))
            elif len(self._data) == 0:
                self._starts[0] = 0
            self._data.extend(encoded)
            return
        pos = self._starts[idx]
        chunk = encoded + b"\n"
        self._data[pos:pos] = chunk
        self._starts[idx] = pos
        self._starts[idx + 1:idx + 1] = array(self._starts.typecode, [pos + len(chunk)])
        for j in range(idx + 2, len(self._starts)):
            self._starts[j] += len(chunk)

    def __delitem__(self, idx: LineIndex) -> None:
        if isinstance(idx, slice):
            indices = list(range(*idx.indices(len(self))))
            if not indices:
                return
            start_i, end_i = min(indices), max(indices)
            # Contiguous slices are what Buffer uses.
            if indices != list(range(start_i, end_i + 1)):
                raise ValueError("non-contiguous deletion not supported")
            start, _ = self._bounds(start_i)
            _, end = self._bounds(end_i)
            if end_i < len(self) - 1:
                end += 1  # remove following newline
            del self._data[start:end]
            count = end_i - start_i + 1
            del self._starts[start_i + 1:end_i + 1]
            delta = end - start
            for j in range(start_i + 1, len(self._starts)):
                self._starts[j] -= delta
            if len(self._starts) == 0:
                self._starts = array("I", [0])
            return
        start, end = self._bounds(idx)
        if idx < len(self) - 1:
            end += 1
        del self._data[start:end]
        del self._starts[idx]
        delta = end - start
        for j in range(idx, len(self._starts)):
            self._starts[j] -= delta
        if len(self._starts) == 0:
            self._starts = array("I", [0])

    def __iter__(self) -> Iterator[str]:
        for i in range(len(self)):
            yield self[i]

    def __eq__(self, other) -> bool:
        if isinstance(other, (list, tuple)):
            return list(self) == list(other)
        if isinstance(other, CompactLines):
            return self._encoding == other._encoding and self._data == other._data
        return NotImplemented
