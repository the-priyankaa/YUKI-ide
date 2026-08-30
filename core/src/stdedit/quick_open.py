"""Quick Open — responsive fuzzy file search engine (stdlib only).

The index is built in a background thread so opening the picker never blocks
curses input.  Results are updated as files are discovered and a direct path
fallback lets an explicitly typed file open even before the background scan
finishes.
"""
from __future__ import annotations

import ctypes
import gc
import os
import sys
import threading
from typing import Iterable, List, Tuple

from . import recent

# Directories that are never indexed — pure junk / huge and never the file
# the user is searching for.
PRUNE_NAMES = {".cache", "Caches", ".Trash", "Trash", ".thumbnails"}

_LIBC = None


def _get_libc():
    """Resolve the C library once; ``None`` when unavailable (non-glibc)."""
    global _LIBC
    if _LIBC is None:
        try:
            _LIBC = ctypes.CDLL(None)
            _LIBC.malloc_trim
        except Exception:
            try:
                _LIBC = ctypes.CDLL("libc.so.6")
                _LIBC.malloc_trim
            except Exception:
                _LIBC = False
    return _LIBC if _LIBC is not False else None


def _free_cached_memory() -> None:
    """Return allocator-cached RSS to the OS after a large index is dropped.

    Python and glibc keep freed pages in their allocators, so a process
    monitor still reports the memory as resident after :meth:`QuickOpen.close`
    clears a big scan.  ``gc.collect()`` plus a guarded ``malloc_trim(0)``
    (Linux/glibc only) reclaims those pages.  A pure no-op everywhere else.
    """
    gc.collect()
    if sys.platform != "linux":
        return
    libc = _get_libc()
    if libc is None:
        return
    try:
        libc.malloc_trim(0)
    except Exception:
        pass

# Top-level names that hold per-app config even though they are not dotted
# (macOS Library/Applications, Windows AppData).  Anything starting with "."
# below the search root is treated as config too.
SECONDARY_ROOT_NAMES = {
    "AppData", "Application Data", "Local Settings", "Library", "Applications",
}

# Ranking constants: tier-0 (visible folder) hits always outrank tier-1
# (config/hidden) hits, and closer files beat deeper ones for equal matches.
TIER_BONUS = 1000.0
DEPTH_PENALTY = 2.5


def _normalize_excludes(exclude_roots: list[str] | None) -> list[str]:
    return [os.path.abspath(os.path.expanduser(p)) for p in (exclude_roots or [])]


def _is_excluded(path: str, excluded: list[str]) -> bool:
    path = os.path.abspath(path)
    return any(path == ex or path.startswith(ex + os.sep) for ex in excluded)


def _classify(root_dir: str, path: str) -> tuple[int, int]:
    """Return ``(tier, depth)`` for *path* relative to *root_dir*.

    tier 0 = visible top-level segment (normal user folder/file).
    tier 1 = config/aux: dot-prefixed top-level segment (``.config``,
    ``.ssh``, …) or a platform config root name (``Library``, ``AppData``).

    depth is the number of path components below *root_dir* (0 for a
    root-level entry) and drives the "nearest file first" ranking.
    """
    rel = os.path.relpath(path, root_dir)
    if rel == os.curdir:
        return 0, 0
    segments = rel.split(os.sep)
    top = segments[0]
    if top.startswith(".") or top in SECONDARY_ROOT_NAMES:
        tier = 1
    else:
        tier = 0
    return tier, len(segments) - 1


def _iter_file_index(
    root_dir: str,
    exclude_roots: list[str] | None = None,
    dirs_only: bool = False,
) -> Iterable[str]:
    """Yield searchable paths under *root_dir* without blocking callers.

    With *dirs_only* True, directories are yielded instead of files (which is
    how the "Open Folder" dashboard action finds folders by name).

    Traversal is ordered so normal (visible) directories are fully walked
    before hidden/config ones: the index cap therefore fills with the user's
    real folders first, and config subtrees always contribute last.
    """
    from .explorer import FileExplorer  # deferred to avoid circular imports

    ignore = FileExplorer.ALWAYS_IGNORED_NAMES
    ignore_suffixes = FileExplorer.ALWAYS_IGNORED_SUFFIXES
    root_dir = os.path.abspath(os.path.expanduser(root_dir))
    excluded = _normalize_excludes(exclude_roots)

    for dirpath, dirnames, filenames in os.walk(root_dir):
        if _is_excluded(dirpath, excluded):
            dirnames[:] = []
            continue

        kept_dirs = []
        for d in dirnames:
            if d in ignore or d in PRUNE_NAMES:
                continue
            if any(d.endswith(s) for s in ignore_suffixes):
                continue
            full = os.path.join(dirpath, d)
            if _is_excluded(full, excluded):
                continue
            kept_dirs.append(d)
            if dirs_only:
                yield full
        # Visible dirs before hidden/config dirs, alphabetical within each.
        dirnames[:] = sorted(kept_dirs, key=lambda d: (d.startswith("."), d))

        if dirs_only:
            continue
        for fname in filenames:
            if any(fname.endswith(s) for s in ignore_suffixes):
                continue
            yield os.path.join(dirpath, fname)


def build_file_index(
    root_dir: str,
    exclude_roots: list[str] | None = None,
    dirs_only: bool = False,
) -> List[str]:
    """Walk *root_dir* and return a sorted list of absolute paths.

    With *dirs_only* True the list contains directories instead of files.
    """
    files = list(_iter_file_index(root_dir, exclude_roots, dirs_only))
    files.sort()
    return files


def _fuzzy_score(query: str, path: str) -> float:
    """Score how well *query* matches *path*.

    Returns a float >= 0 (higher is better) or -1 for no match.
    """
    if not query:
        return 0.0

    q_lower = query.lower()
    basename = os.path.basename(path).lower()
    full_lower = path.lower()

    qi = 0
    matches: list[int] = []
    for i, ch in enumerate(full_lower):
        if qi < len(q_lower) and ch == q_lower[qi]:
            matches.append(i)
            qi += 1
    if qi < len(q_lower):
        return -1.0

    score = 0.0
    max_run = 1
    cur_run = 1
    for j in range(1, len(matches)):
        if matches[j] == matches[j - 1] + 1:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    score += max_run * 10.0

    span = matches[-1] - matches[0] + 1
    score -= span * 0.5

    basename_start = path.rfind(os.sep) + 1
    in_basename = all(m >= basename_start for m in matches)
    if in_basename:
        score += 20.0

    if basename.startswith(q_lower):
        score += 30.0

    score -= len(path) * 0.01
    return score


def fuzzy_search(query: str, files: List[str], limit: int = 20) -> List[Tuple[float, str]]:
    """Return up to *limit* ``(score, path)`` tuples sorted best-first."""
    if not query:
        return []
    return _fuzzy_search_lowered(query, files, [p.lower() for p in files], limit)


def _fuzzy_search_lowered(
    query: str, files: Iterable[str], lowers: Iterable[str], limit: int = 20,
    tiers: Iterable[int] | None = None, depths: Iterable[float] | None = None,
) -> List[Tuple[float, str]]:
    """Score *files* reusing precomputed lowercase forms.

    Identical scoring to :func:`fuzzy_search` but avoids re-lowercasing every
    path on each keystroke, which dominates allocation and CPU cost.

    When *tiers* / *depths* are given, indexing results learn the "nearest
    first, config last" ranking: tier-0 (visible folder) hits always outrank
    tier-1 (config/hidden) hits via :data:`TIER_BONUS`, and shallower paths
    outrank deeper ones via :data:`DEPTH_PENALTY`.  Both are optional so the
    public :func:`fuzzy_search` path keeps its exact historical behaviour.
    """
    if not query:
        return []

    q_lower = query.lower()
    scored: list[tuple[float, str]] = []
    tier_iter = iter(tiers) if tiers is not None else None
    depth_iter = iter(depths) if depths is not None else None
    for path, full_lower in zip(files, lowers):
        # Advance the tier/depth iterators in lockstep with *every* path so a
        # non-matching file never shifts later files onto the wrong tier.
        tier = next(tier_iter) if tier_iter is not None else None
        depth = next(depth_iter) if depth_iter is not None else None
        qi = 0
        matches: list[int] = []
        for i, ch in enumerate(full_lower):
            if qi < len(q_lower) and ch == q_lower[qi]:
                matches.append(i)
                qi += 1
        if qi < len(q_lower):
            continue

        score = 0.0
        max_run = 1
        cur_run = 1
        for j in range(1, len(matches)):
            if matches[j] == matches[j - 1] + 1:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 1
        score += max_run * 10.0

        span = matches[-1] - matches[0] + 1
        score -= span * 0.5

        basename_start = path.rfind(os.sep) + 1
        if all(m >= basename_start for m in matches):
            score += 20.0

        if full_lower.startswith(q_lower, basename_start):
            score += 30.0

        score -= len(path) * 0.01
        if tier is not None:
            score += TIER_BONUS if tier == 0 else 0.0
            score -= depth * DEPTH_PENALTY
        scored.append((score, path))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:limit]





class QuickOpen:
    """Responsive Quick Open overlay state with async indexing + scoring.

    Both the file index build and the per-keystroke result scoring run on
    background worker threads, so typing never blocks the TUI.  The index is
    capped (:attr:`MAX_FILES`) so memory and worst-case recompute stay bounded.
    """

    BATCH_SIZE = 256
    MAX_FILES = 40_000

    # A scan releases a large parallel index on close(); above this many
    # files the allocator-cached RSS is worth returning to the OS.
    CLOSE_TRIM_THRESHOLD = 4_000

    def __init__(
        self,
        root_dir: str = ".",
        exclude_roots: list[str] | None = None,
        show_recent_on_empty: bool = False,
        mode: str = "files",
    ) -> None:
        self.root_dir: str = os.path.abspath(os.path.expanduser(root_dir))
        self.exclude_roots: list[str] = list(exclude_roots or [])
        self.mode: str = mode  # "files" or "folders" (folders-only picker)
        self.files: list[str] = []
        self.query: str = ""
        self.results: list[tuple[float, str]] = []
        self.selected_idx: int = 0
        self.visible: bool = False
        self.show_recent_on_empty = show_recent_on_empty
        self.loading: bool = False
        self.scan_error: str | None = None
        self.capped: bool = False
        self.scoring: bool = False
        self._lowers: list[str] = []
        self.tiers: list[int] = []
        self.depths: list[float] = []
        self._scan_thread: threading.Thread | None = None
        self._results_thread: threading.Thread | None = None
        self._scan_stop = threading.Event()
        self._results_stop = threading.Event()
        self._query_wake = threading.Event()
        self._generation = 0
        self._query_dirty = False
        self._files_version = 0
        self._last_version = 0
        self._lock = threading.RLock()

    def _flush_scan_batch(self, batch: list[tuple[str, str, int, int]],
                          generation: int,
                          stop_event: threading.Event) -> None:
        if not batch:
            return
        with self._lock:
            if generation != self._generation or stop_event.is_set():
                return
            self.files.extend(p for p, _, _, _ in batch)
            self._lowers.extend(l for _, l, _, _ in batch)
            self.tiers.extend(t for _, _, t, _ in batch)
            self.depths.extend(d for _, _, _, d in batch)
            self._files_version += 1
            self._query_wake.set()

    def _scan_worker(self, stop_event: threading.Event, generation: int) -> None:
        try:
            batch: list[tuple[str, str, int, int]] = []
            count = 0
            for path in _iter_file_index(
                self.root_dir, self.exclude_roots,
                dirs_only=(self.mode == "folders"),
            ):
                if stop_event.is_set():
                    return
                if count >= self.MAX_FILES:
                    with self._lock:
                        if generation == self._generation and not stop_event.is_set():
                            self.capped = True
                    break
                tier, depth = _classify(self.root_dir, path)
                batch.append((path, path.lower(), tier, depth))
                count += 1
                if len(batch) >= self.BATCH_SIZE:
                    self._flush_scan_batch(batch, generation, stop_event)
                    batch.clear()
            self._flush_scan_batch(batch, generation, stop_event)
            with self._lock:
                if generation == self._generation and not stop_event.is_set():
                    pairs = sorted(
                        zip(self.files, self._lowers, self.tiers, self.depths),
                        key=lambda p: p[0])
                    self.files = [p[0] for p in pairs]
                    self._lowers = [p[1] for p in pairs]
                    self.tiers = [p[2] for p in pairs]
                    self.depths = [p[3] for p in pairs]
                    self._files_version += 1
                    self.loading = False
                    self._query_wake.set()
        except Exception as exc:  # defensive: search must never kill the TUI
            with self._lock:
                if generation == self._generation and not stop_event.is_set():
                    self.scan_error = str(exc)
                    self.loading = False

    def _results_worker(self, stop_event: threading.Event, generation: int) -> None:
        while True:
            with self._lock:
                if generation != self._generation or stop_event.is_set():
                    return
                stale = self._query_dirty or (
                    bool(self.query) and self._files_version != self._last_version
                )
                if not stale:
                    self.scoring = False
            if not stale:
                if self._query_wake.wait(0.05):
                    self._query_wake.clear()
                continue

            with self._lock:
                self._query_wake.clear()
                self._query_dirty = False
                self.scoring = True
                query = self.query
                files = tuple(self.files)
                lowers = tuple(self._lowers)
                tiers = tuple(self.tiers)
                depths = tuple(self.depths)
                version = self._files_version
            if query:
                results = _fuzzy_search_lowered(
                    query, files, lowers, tiers=tiers, depths=depths)
            else:
                results = []
            with self._lock:
                if (generation == self._generation and not stop_event.is_set()
                        and self.query == query):
                    self.results = results
                    self.selected_idx = min(self.selected_idx, max(0, len(self.results) - 1))
                    self._last_version = version
                self.scoring = False

    def open(self, background_index: bool = True) -> None:
        """Show the overlay immediately; optionally index files in the background."""
        self._scan_stop.set()
        self._results_stop.set()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self.files = []
            self._lowers = []
            self.tiers = []
            self.depths = []
            self.query = ""
            self.results = []
            self.selected_idx = 0
            self.scan_error = None
            self.capped = False
            self.scoring = False
            self._query_dirty = False
            self._files_version = 0
            self._last_version = 0
            self.visible = True
            self.loading = bool(background_index)
        self._scan_stop = threading.Event()
        self._results_stop = threading.Event()
        self._query_wake = threading.Event()
        if not background_index:
            return
        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(self._scan_stop, generation),
            name="stdedit-quick-open-index",
            daemon=True,
        )
        self._results_thread = threading.Thread(
            target=self._results_worker,
            args=(self._results_stop, generation),
            name="stdedit-quick-open-results",
            daemon=True,
        )
        self._scan_thread.start()
        self._results_thread.start()

    def close(self) -> None:
        """Hide the overlay and stop any outstanding scan/rescore workers."""
        self._scan_stop.set()
        self._results_stop.set()
        self._query_wake.set()
        for thread in (self._scan_thread, self._results_thread):
            if thread is not None:
                thread.join(timeout=0.5)
        self._scan_thread = None
        self._results_thread = None
        with self._lock:
            trim = len(self.files) >= self.CLOSE_TRIM_THRESHOLD
            self.visible = False
            self.query = ""
            self.results = []
            self.selected_idx = 0
            self.loading = False
            self.scoring = False
            self.files = []
            self._lowers = []
            self.tiers = []
            self.depths = []
            self._files_version = 0
            self._last_version = 0
        if trim:
            # Return the dropped index's cached pages to the OS so the RAM
            # meter / task manager reflects the search box being closed.
            _free_cached_memory()

    def update_query(self, query: str) -> None:
        """Record a new query without blocking the caller.

        The recompute happens on the results worker thread; typing therefore
        never stalls the TUI even with a large index.
        """
        with self._lock:
            if self.query == query:
                return
            self.query = query
            self._query_dirty = True
        self._query_wake.set()

    def move_selection(self, dy: int) -> None:
        """Move cursor up/down, clamped to results."""
        with self._lock:
            total = len(self.results)
            if total:
                self.selected_idx = max(0, min(self.selected_idx + dy, total - 1))

    def _typed_paths(self) -> list[str]:
        """Resolve the typed query into candidate absolute paths."""
        query = self.query.strip()
        if not query:
            return []
        if os.path.isabs(query):
            return [os.path.abspath(os.path.expanduser(query))]
        candidates = [os.path.abspath(os.path.join(self.root_dir, query))]
        if os.sep not in query:
            candidates.append(os.path.abspath(os.path.expanduser("~") + os.sep + query))
        return candidates

    def _direct_candidate(self) -> str | None:
        """Resolve an explicitly typed existing path without waiting for indexing."""
        for path in self._typed_paths():
            if not os.path.isfile(path):
                continue
            if _is_excluded(path, _normalize_excludes(self.exclude_roots)):
                continue
            return path
        return None

    def _direct_folder(self) -> str | None:
        """Resolve an explicitly typed existing directory (e.g. to open as root)."""
        for path in self._typed_paths():
            if not os.path.isdir(path):
                continue
            if _is_excluded(path, _normalize_excludes(self.exclude_roots)):
                continue
            return path
        return None

    def selected_path(self) -> str | None:
        """Return selected result, or a directly typed existing path."""
        with self._lock:
            if 0 <= self.selected_idx < len(self.results):
                return self.results[self.selected_idx][1]
            return self._direct_candidate()

    def selected_location(self) -> str | None:
        """Return the typed existing path (file or folder) when it resolves,
        otherwise the selected fuzzy result.

        An explicitly typed location wins over fuzzy subpath matches so that
        entering a real path always opens that path rather than an unrelated
        partial-match result.  In folders mode only directories are accepted.
        """
        with self._lock:
            typed_only_folder = self._direct_folder()
            typed_only_file = self._direct_candidate()
            if self.mode == "folders":
                if typed_only_folder:
                    return typed_only_folder
                if 0 <= self.selected_idx < len(self.results):
                    path = self.results[self.selected_idx][1]
                    return path if os.path.isdir(path) else None
                return None
            if typed_only_file or typed_only_folder:
                return typed_only_file or typed_only_folder
            if 0 <= self.selected_idx < len(self.results):
                return self.results[self.selected_idx][1]
            return None

    def get_display_items(self, limit: int = 20) -> list[tuple[str, bool]]:
        """Return display items without exposing a partially-written list."""
        with self._lock:
            if not self.query:
                if not self.show_recent_on_empty or self.mode == "folders":
                    return []
                existing = [p for p in recent.get_recent() if os.path.isfile(p)][:limit]
                return [(p, False) for p in existing]

            return [
                (path, i == self.selected_idx)
                for i, (_, path) in enumerate(self.results[:limit])
            ]