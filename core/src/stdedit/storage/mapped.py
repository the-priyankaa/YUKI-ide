"""Low-RSS, read-mostly line store backed by the source file.

Large files start here. The file is memory-mapped read-only and line offsets
are stored compactly. The first mutation transparently materializes the file
into CompactLines, so ordinary editing semantics stay unchanged.
"""
from __future__ import annotations

from array import array
import mmap
import os
from typing import Callable, Iterator


class MappedLines:
    __slots__ = ("_path", "_encoding", "_mm", "_starts", "_materialize")

    def __init__(self, path: str, encoding: str, materialize: Callable[[], object]) -> None:
        self._path = path
        self._encoding = encoding
        self._materialize = materialize
        self._starts = self._build_index(path)
        self._mm = None
        fd = os.open(path, os.O_RDONLY)
        try:
            size = os.fstat(fd).st_size
            self._mm = mmap.mmap(fd, size, access=mmap.ACCESS_READ) if size else None
        finally:
            os.close(fd)

    @staticmethod
    def _build_index(path: str):
        size = os.path.getsize(path)
        IndexType = "I" if size <= 0xFFFFFFFF else "Q"
        starts = array(IndexType, [0])
        if size == 0:
            return starts
        pos = 0
        carry = b""
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                data = carry + chunk
                base = pos - len(carry)
                off = 0
                while True:
                    nl = data.find(b"\n", off)
                    if nl < 0:
                        break
                    starts.append(base + nl + 1)
                    off = nl + 1
                carry = data[off:]
                pos += len(chunk)
        # A trailing newline already creates the final empty line by the
        # appended file-end offset. A non-newline file does not need another.
        return starts

    def __len__(self) -> int:
        return len(self._starts)

    def _bounds(self, idx: int):
        if idx < 0:
            idx += len(self)
        if idx < 0 or idx >= len(self):
            raise IndexError(idx)
        start = self._starts[idx]
        end = self._starts[idx + 1] - 1 if idx + 1 < len(self) else len(self._mm) if self._mm is not None else 0
        if end > start and self._mm[end - 1:end] == b"\r":
            end -= 1
        return start, end

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return [self[i] for i in range(*idx.indices(len(self)))]
        start, end = self._bounds(idx)
        if self._mm is None:
            return ""
        return self._mm[start:end].decode(self._encoding)

    def _editable(self):
        return self._materialize()

    def __setitem__(self, idx, value):
        store = self._editable()
        store[idx] = value

    def insert(self, idx, value):
        store = self._editable()
        store.insert(idx, value)

    def __delitem__(self, idx):
        store = self._editable()
        del store[idx]

    def __iter__(self) -> Iterator[str]:
        for i in range(len(self)):
            yield self[i]

    def __eq__(self, other):
        if isinstance(other, (list, tuple)):
            return list(self) == list(other)
        return NotImplemented

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None
