"""YellowDB memtable module.

Provides in-memory data structures that act as fast write buffers for the database.
Memtables are maintained in sorted order to enable efficient range queries and
are flushed to disk as SSTables when they reach a size threshold.

Supports both single memtable and concurrent multi-memtable configurations
for improved write parallelism.
"""

import threading
import time
from typing import Dict, List, Optional, Tuple

from sortedcontainers import SortedDict

from ..utils.config import Config


class MemtableEntry:
    """A single entry in a memtable.

    Represents a key-value pair along with metadata for versioning and
    deletion tracking. Uses __slots__ for memory efficiency.

    Attributes:
        key: The string key
        value: The bytes value
        timestamp: Write timestamp for versioning
        deleted: Whether this entry represents a deletion

    Example:
        >>> entry = MemtableEntry("user:1", b"Alice", timestamp=12345)
        >>> deleted_entry = MemtableEntry("user:1", b"", timestamp=12346, deleted=True)

    """

    __slots__ = ("key", "value", "timestamp", "deleted")

    def __init__(self, key: str, value: bytes, timestamp: int, deleted: bool = False):
        """Initialize a memtable entry.

        Args:
            key: The key string
            value: The value bytes
            timestamp: Write timestamp for this entry
            deleted: Whether this is a deletion marker

        """
        self.key = key
        self.value = value
        self.timestamp = timestamp
        self.deleted = deleted

    def __repr__(self) -> str:
        """Get string representation of the entry.

        Returns:
            String showing key, timestamp, and deleted status

        """
        return f"MemtableEntry(key={self.key}, ts={self.timestamp}, deleted={self.deleted})"


class BufferPool:
    """Object pool for reusable byte buffers.

    Reduces memory allocation overhead by maintaining a pool of pre-allocated
    bytearray buffers that can be reused for I/O operations.

    Attributes:
        buffer_size: Size of each buffer in bytes
        pool_size: Number of buffers to maintain in the pool
        _available: List of available buffers

    Example:
        >>> pool = BufferPool(buffer_size=1024*1024, pool_size=4)
        >>> buffer = pool.acquire()
        >>> buffer.clear()  # Use buffer
        >>> pool.release(buffer)

    """

    def __init__(self, buffer_size: int = 1024 * 1024, pool_size: int = 4):
        """Initialize the buffer pool.

        Args:
            buffer_size: Size in bytes for each buffer (default 1MB)
            pool_size: Number of buffers to keep in the pool (default 4)

        """
        self.buffer_size = buffer_size
        self.pool_size = pool_size

        self._lock = threading.Lock()
        self._buffers: List[bytearray] = [bytearray(buffer_size) for _ in range(pool_size)]
        self._available: List[bytearray] = self._buffers.copy()

    def acquire(self) -> bytearray:
        """Acquire a buffer from the pool.

        Returns a pre-allocated buffer from the pool if available,
        otherwise allocates a new buffer.

        Returns:
            A bytearray buffer of the configured size

        Thread-safe: Uses lock for concurrent access

        """
        with self._lock:
            if self._available:
                return self._available.pop()
            return bytearray(self.buffer_size)

    def release(self, buffer: bytearray) -> None:
        """Release a buffer back to the pool.

        Returns a buffer to the pool if it's the correct size and the pool
        has space. Otherwise, the buffer is discarded.

        Args:
            buffer: The bytearray to return to the pool

        Thread-safe: Uses lock for concurrent access

        """
        if len(buffer) == self.buffer_size:
            with self._lock:
                if len(self._available) < self.pool_size:
                    buffer.clear()
                    self._available.append(buffer)


class Memtable:
    """In-memory sorted write buffer for fast writes.

    Maintains all recently written key-value pairs in sorted order using
    SortedDict. When the memtable reaches the configured size, it is flushed
    to disk as an SSTable. Supports concurrent access via locking.

    Attributes:
        _data: SortedDict mapping keys to MemtableEntry objects
        _size: Total size of values in the memtable in bytes
        _entry_count: Number of entries added (includes overwrites)
        _created_at: Creation timestamp for age tracking
        config: Configuration instance

    Example:
        >>> memtable = Memtable()
        >>> memtable.put("key1", b"value1", timestamp=100)
        >>> entry = memtable.get("key1")
        >>> if memtable.is_full():
        ...     entries = memtable.get_sorted_entries()
        ...     memtable.clear()

    """

    def __init__(self):
        """Initialize a new memtable.

        Creates an empty sorted data structure and initializes metadata.
        """
        self.config = Config()

        self._lock = threading.RLock()
        self._data: SortedDict = SortedDict()
        self._size = 0
        self._entry_count = 0
        self._created_at = time.time()
        self._buffer_pool = BufferPool()

    def put(self, key: str, value: bytes, timestamp: int, deleted: bool = False) -> None:
        """Store or update a key-value pair.

        Updates the size tracking to account for replacements. If the key
        already exists, the old size is subtracted before adding the new size.

        Args:
            key: The key string
            value: The value bytes
            timestamp: Write timestamp
            deleted: Whether this is a deletion marker

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            old_size = 0
            if key in self._data:
                old_entry = self._data[key]
                old_size = len(old_entry.key.encode("utf-8")) + len(old_entry.value)

            new_entry = MemtableEntry(key, value, timestamp, deleted)
            new_size = len(key.encode("utf-8")) + len(value)
            self._size += new_size - old_size

            self._data[key] = new_entry
            self._entry_count += 1

    def get(self, key: str) -> Optional[MemtableEntry]:
        """Retrieve an entry by key.

        Args:
            key: The key to look up

        Returns:
            MemtableEntry if found, None otherwise

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return self._data.get(key)

    def delete(self, key: str, timestamp: int) -> None:
        """Mark a key as deleted.

        Creates a delete marker entry so the deletion is tracked and can
        be propagated to disk and other components.

        Args:
            key: The key to delete
            timestamp: Delete timestamp

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            self.put(key, b"", timestamp, deleted=True)

    def clear(self) -> None:
        """Clear all entries from the memtable.

        Resets the memtable to empty state. Used after flushing to disk.

        Thread-safe: Uses RLock for concurrent access
        """
        with self._lock:
            self._data.clear()
            self._size = 0
            self._entry_count = 0

    def get_all(self) -> Dict[str, MemtableEntry]:
        """Get all entries as a dictionary.

        Returns a shallow copy of all memtable entries.

        Returns:
            Dictionary mapping keys to MemtableEntry objects

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return dict(self._data)

    def get_sorted_entries(self) -> List[Tuple[str, MemtableEntry]]:
        """Get all entries as a sorted list of (key, entry) tuples.

        Returns entries in sorted key order, useful for flushing to disk.

        Returns:
            List of (key, MemtableEntry) tuples in sorted order

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return [(key, entry) for key, entry in self._data.items()]

    def get_size(self) -> int:
        """Get the total size of all values in the memtable.

        Returns:
            Size in bytes of all stored values

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return self._size

    def get_count(self) -> int:
        """Get the number of unique keys in the memtable.

        Returns:
            Number of entries in the memtable

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return len(self._data)

    def get_age(self) -> float:
        """Get the age of this memtable in seconds.

        Returns:
            Seconds since memtable creation

        """
        return time.time() - self._created_at

    def is_full(self) -> bool:
        """Check if the memtable has exceeded the configured size limit.

        Returns:
            True if memtable size >= configured memtable_size

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return self._size >= self.config.memtable_size

    def range_query(self, start_key: str, end_key: str) -> List[MemtableEntry]:
        """Get all entries within a key range.

        Returns entries for keys >= start_key and <= end_key in sorted order.

        Args:
            start_key: Starting key (inclusive)
            end_key: Ending key (inclusive)

        Returns:
            List of MemtableEntry objects in the range

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            result = []
            try:
                for key in self._data.irange(start_key, end_key):
                    result.append(self._data[key])
            except Exception:
                pass
            return result

    def __len__(self) -> int:
        """Get the number of entries in the memtable.

        Returns:
            Number of entries

        """
        return len(self._data)

    def __contains__(self, key: str) -> bool:
        """Check if a key exists in the memtable.

        Args:
            key: The key to check

        Returns:
            True if key exists, False otherwise

        Thread-safe: Uses RLock for concurrent access

        """
        with self._lock:
            return key in self._data

    def __repr__(self) -> str:
        """Get string representation of the memtable.

        Returns:
            String showing entry count, total size, and age

        """
        with self._lock:
            return f"Memtable(entries={len(self._data)}, size={self._size}B, age={self.get_age():.2f}s)"


class ConcurrentMemtables:
    """Multiple memtables for concurrent write operations.

    Uses hash-based sharding to distribute writes across multiple memtables,
    enabling higher write throughput in multi-threaded scenarios. Each key
    is assigned to a memtable based on its hash.

    Attributes:
        memtables: List of Memtable instances
        count: Number of memtables in the collection

    Example:
        >>> concurrent = ConcurrentMemtables(count=4)
        >>> concurrent.put("key1", b"value1", timestamp=100)
        >>> concurrent.put("key2", b"value2", timestamp=101)
        >>> full_tables = concurrent.get_full_memtables()

    """

    def __init__(self, count: int = 4):
        """Initialize concurrent memtables.

        Args:
            count: Number of memtables to create (default 4)

        """
        self.memtables = [Memtable() for _ in range(count)]
        self.count = count

        self._lock = threading.RLock()

    def _get_memtable_index(self, key: str) -> int:
        """Get the memtable index for a key based on hash.

        Args:
            key: The key to hash

        Returns:
            Index of the memtable for this key (0 to count-1)

        """
        return hash(key) % self.count

    def put(self, key: str, value: bytes, timestamp: int, deleted: bool = False) -> None:
        """Store a key-value pair in the appropriate memtable.

        Args:
            key: The key
            value: The value
            timestamp: Write timestamp
            deleted: Whether this is a deletion marker

        """
        index = self._get_memtable_index(key)
        self.memtables[index].put(key, value, timestamp, deleted)

    def get(self, key: str) -> Optional[MemtableEntry]:
        """Retrieve an entry from the appropriate memtable.

        Args:
            key: The key to look up

        Returns:
            MemtableEntry if found, None otherwise

        """
        index = self._get_memtable_index(key)
        return self.memtables[index].get(key)

    def delete(self, key: str, timestamp: int) -> None:
        """Mark a key as deleted in the appropriate memtable.

        Args:
            key: The key to delete
            timestamp: Delete timestamp

        """
        index = self._get_memtable_index(key)
        self.memtables[index].delete(key, timestamp)

    def clear_memtable(self, index: int) -> None:
        """Clear a specific memtable.

        Used after flushing a memtable to disk.

        Args:
            index: Index of the memtable to clear (0 to count-1)

        """
        self.memtables[index].clear()

    def clear_all(self) -> None:
        """Clear all memtables.

        Resets all memtables to empty state.
        """
        for memtable in self.memtables:
            memtable.clear()

    def get_all_entries(self) -> Dict[str, MemtableEntry]:
        """Get all entries from all memtables.

        Returns:
            Dictionary mapping keys to MemtableEntry objects from all memtables

        """
        result = {}
        for memtable in self.memtables:
            result.update(memtable.get_all())
        return result

    def get_total_size(self) -> int:
        """Get the total size of all memtables.

        Returns:
            Combined size in bytes of all memtables

        """
        return sum(memtable.get_size() for memtable in self.memtables)

    def get_full_memtables(self) -> List[Tuple[int, Memtable]]:
        """Get all memtables that have reached the size threshold.

        Returns:
            List of (index, memtable) tuples for full memtables

        """
        return [(i, memtable) for i, memtable in enumerate(self.memtables) if memtable.is_full()]

    def __repr__(self) -> str:
        """Get string representation of concurrent memtables.

        Returns:
            String showing count and total size

        """
        return f"ConcurrentMemtables(count={self.count}, total_size={self.get_total_size()})"
