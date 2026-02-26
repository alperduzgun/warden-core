"""
Thread-safe LRU Cache.

Provides a dict-like container with a maximum size limit and
least-recently-used eviction policy.  Every read (``__getitem__``,
``get``, ``__contains__``) promotes the accessed entry so it becomes
the *most* recently used; when a new insertion would exceed *maxsize*,
the least-recently-used entry is silently discarded.

The implementation is built on ``collections.OrderedDict`` and is
protected by a ``threading.Lock`` so it is safe for concurrent use
from multiple pipeline phases/threads.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Iterator


class LRUCache:
    """
    A bounded, thread-safe, dict-like LRU cache.

    Parameters
    ----------
    maxsize : int
        Maximum number of entries.  When exceeded the least-recently-used
        entry is evicted.  Must be >= 1.

    Examples
    --------
    >>> cache = LRUCache(maxsize=3)
    >>> cache["a"] = 1
    >>> cache["b"] = 2
    >>> cache["c"] = 3
    >>> cache["d"] = 4          # evicts "a"
    >>> "a" in cache
    False
    >>> cache.get("b")          # promotes "b"
    2
    """

    __slots__ = ("_maxsize", "_data", "_lock")

    def __init__(self, maxsize: int = 500) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize must be >= 1, got {maxsize}")
        self._maxsize = maxsize
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    # -- dict-like read operations (promote on access) ---------------------

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            value = self._data[key]  # raises KeyError if absent
            self._data.move_to_end(key)
            return value

    def __contains__(self, key: object) -> bool:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)  # type: ignore[arg-type]
                return True
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key* if present (promoting it), else *default*."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            return default

    # -- dict-like write operations ----------------------------------------

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = value
            else:
                self._data[key] = value
                if len(self._data) > self._maxsize:
                    self._data.popitem(last=False)  # evict LRU

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._data[key]

    # -- size & iteration --------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._data)

    def __iter__(self) -> Iterator[str]:
        """Iterate over keys (snapshot, no promotion)."""
        with self._lock:
            return iter(list(self._data.keys()))

    def keys(self):
        """Return a snapshot of keys (no promotion)."""
        with self._lock:
            return list(self._data.keys())

    def values(self):
        """Return a snapshot of values (no promotion)."""
        with self._lock:
            return list(self._data.values())

    def items(self):
        """Return a snapshot of (key, value) pairs (no promotion)."""
        with self._lock:
            return list(self._data.items())

    # -- utility -----------------------------------------------------------

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._data.clear()

    @property
    def maxsize(self) -> int:
        """Return the configured maximum size."""
        return self._maxsize

    def __repr__(self) -> str:
        with self._lock:
            return f"LRUCache(maxsize={self._maxsize}, len={len(self._data)})"
