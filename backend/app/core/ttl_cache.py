"""Thread-safe in-memory TTL cache with persistent per-key single-flight locking.

Design rules:
- Standard library only (`threading`, `time`, `typing`) plus Pydantic `model_copy(deep=True)`.
- `_meta_lock` protects only fast in-memory dictionary operations (never held during I/O).
- Persistent per-key locks serialize concurrent cold-cache fetches for the same key while
  allowing unrelated keys to fetch fully in parallel.
- `clear()` removes cached entries under `_meta_lock` without deleting or replacing per-key
  locks, preventing lock-replacement races while threads are waiting or fetching.
- Strict lock hierarchy (`key_lock -> _meta_lock`) guarantees freedom from deadlocks.
"""

from __future__ import annotations

import threading
import time
from typing import Generic, Hashable, TypeVar

from pydantic import BaseModel

K = TypeVar("K", bound=Hashable)
V = TypeVar("V", bound=BaseModel)


class _TTLEntry(Generic[V]):
    """Immutable-by-convention TTL cache entry."""

    __slots__ = ("expires_at", "value")

    def __init__(self, value: V, expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at


class SingleFlightTTLCache(Generic[K, V]):
    """Bounded-keyspace thread-safe TTL cache with persistent per-key locks."""

    def __init__(self) -> None:
        self._meta_lock = threading.Lock()
        self._entries: dict[K, _TTLEntry[V]] = {}
        self._key_locks: dict[K, threading.Lock] = {}

    def get(self, key: K) -> V | None:
        """Return a deep copy of a non-expired cached value, or None on miss/expiry."""
        now = time.monotonic()
        with self._meta_lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            stored_value = entry.value

        return stored_value.model_copy(deep=True)

    def set(self, key: K, value: V, ttl_seconds: float) -> None:
        """Store a deep copy of `value` with expiry computed from current monotonic time."""
        if ttl_seconds <= 0:
            return
        snapshot = value.model_copy(deep=True)
        expires_at = time.monotonic() + float(ttl_seconds)
        with self._meta_lock:
            self._entries[key] = _TTLEntry(snapshot, expires_at)

    def key_lock(self, key: K) -> threading.Lock:
        """Return the persistent per-key lock for `key` without holding `_meta_lock` during I/O."""
        with self._meta_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def clear(self) -> None:
        """Clear all cached entries safely while preserving persistent per-key locks."""
        with self._meta_lock:
            self._entries.clear()
