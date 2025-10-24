"""YellowDB write-through cache module.

Provides a write-through caching layer that sits between the database and the
user. All writes immediately update the cache, and reads check the cache first
before looking in the memtable or SSTables.
"""

import threading
from collections import OrderedDict
from typing import Optional, Tuple

from ..utils.config import Config


class WriteThroughCache:
    """Write-through cache for frequently accessed key-value pairs.

    Implements an LRU (Least Recently Used) eviction policy using OrderedDict.
    When the cache reaches maximum size, the least recently used items are evicted.
    All writes go through the cache, ensuring cache coherency.

    Attributes:
        maximum_size: Maximum size in bytes for cached data
        _cache: OrderedDict storing (key, (value, timestamp, deleted))
        _size: Current total size of cached values in bytes
        _lock: RLock for thread-safe operations

    Example:
        >>> cache = WriteThroughCache(max_size=1024*1024)
        >>> cache.put("key1", b"value1", timestamp=100)
        >>> result = cache.get("key1")
        >>> cache.invalidate("key1")

    """

    def __init__(self, max_size: int = None):
        """Initialize the cache.

        Args:
            max_size: Maximum size in bytes. If None, uses default from Config.
                     When cache exceeds this size, LRU items are evicted.

        """
        self.config = Config()
        self.maximum_size = max_size or self.config.cache_size

        self._lock = threading.RLock()
        self._cache: OrderedDict[str, Tuple[bytes, int, bool]] = OrderedDict()
        self._size = 0

    def put(self, key: str, value: bytes, timestamp: int, deleted: bool = False) -> None:
        """Store or update a key-value pair in the cache.

        If the key already exists, it is moved to the end (most recently used).
        When the cache exceeds maximum size, least recently used items are evicted.

        Args:
            key: The key to store
            value: The value to cache
            timestamp: Timestamp when this entry was written
            deleted: Whether this entry represents a deletion

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            if key in self._cache:
                old_value, _, _ = self._cache[key]
                self._size -= len(old_value)
                del self._cache[key]

            self._cache[key] = (value, timestamp, deleted)
            self._size += len(value)

            self._cache.move_to_end(key)

            while self._size > self.maximum_size and len(self._cache) > 0:
                oldest_key, (oldest_value, _, _) = self._cache.popitem(last=False)
                self._size -= len(oldest_value)

    def get(self, key: str) -> Optional[Tuple[bytes, int, bool]]:
        """Retrieve a value from the cache.

        Updates the LRU position of the accessed key to mark it as recently used.

        Args:
            key: The key to retrieve

        Returns:
            Tuple of (value, timestamp, deleted) if key exists, None otherwise

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def invalidate(self, key: str) -> None:
        """Remove a key from the cache.

        Called when a key is updated or deleted in the database to maintain
        cache coherency.

        Args:
            key: The key to remove from cache

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            if key in self._cache:
                value, _, _ = self._cache[key]
                self._size -= len(value)
                del self._cache[key]

    def clear(self) -> None:
        """Clear all entries from the cache.

        Resets the cache to an empty state without resizing.

        Thread-safe: Uses RLock for concurrent access
        """
        with self._lock:
            self._cache.clear()
            self._size = 0

    def get_count(self) -> int:
        """Get the number of entries currently in the cache.

        Returns:
            Number of cached entries

        """
        return len(self._cache)

    def get_size(self) -> int:
        """Get the current total size of cached data in bytes.

        Returns:
            Total size of all cached values in bytes

        """
        return self._size

    def __repr__(self) -> str:
        """Get string representation of the cache.

        Returns:
            String showing entry count and total size

        """
        return f"WriteThroughCache(entries={len(self._cache)}, size={self._size}B)"
