"""YellowDB main database module.

This module contains the core YellowDB class that provides the main API for
key-value storage operations using Log-Structured Merge-tree (LSM-tree) architecture.

The YellowDB class manages:
- In-memory write buffers (memtables)
- On-disk sorted string tables (SSTables)
- Write-ahead logging (WAL) for durability
- Automatic compaction
- Caching and bloom filters
"""

import threading
import time
from typing import Any, Dict, Optional

from ..cache.write_through import WriteThroughCache
from ..compaction.compactor import Compactor
from ..core.serializer import Serializer
from ..storage.memtable import ConcurrentMemtables, Memtable
from ..storage.sstable import SSTable
from ..storage.wal import WAL
from ..utils.config import Config
from ..utils.exceptions import DatabaseClosedError, InvalidKeyError, InvalidValueError
from .iterator import DatabaseIterator, RangeIterator


class YellowDB:
    """High-performance Log-Structured Merge-tree (LSM-tree) based key-value database.

    YellowDB is an embedded, pure Python database that implements the LSM-tree
    architecture for efficient write-heavy workloads. It provides ACID-like semantics
    with write-ahead logging, concurrent operations, and automatic compaction.

    Attributes:
        config: Configuration instance for database parameters
        data_directory: Path to the directory containing database files
        memtable: In-memory write buffer for pending writes
        wal: Write-ahead log for crash recovery
        compactor: Background compaction manager
        cache: Write-through cache for frequently accessed data

    Example:
        Create and use a database:

        >>> db = YellowDB(data_directory="./my_database")
        >>> db.set("key", b"value")
        >>> value = db.get("key")
        >>> db.close()

        Or use with context manager:

        >>> with YellowDB(data_directory="./my_database") as db:
        ...     db.set("key", b"value")

    """

    def __init__(self, data_directory: Optional[str] = None):
        """Initialize a YellowDB instance.

        Args:
            data_directory: Path to store database files. If None, uses default
                from configuration. Creates directory if it doesn't exist.

        Raises:
            IOError: If directory creation fails

        """
        self.config = Config()

        if data_directory:
            self.config.set_data_directory(data_directory)

        self.data_directory = self.config.data_directory
        self.data_directory.mkdir(parents=True, exist_ok=True)

        self._closed = False
        self._lock = threading.RLock()
        self._compaction_lock = threading.Lock()

        if self.config.enable_concurrent_memtables:
            self.memtable = ConcurrentMemtables(self.config.concurrent_memtable_count)
        else:
            self.memtable = Memtable()

        self.wal = WAL(self.data_directory)
        self.compactor = Compactor(self.data_directory)
        self.cache = WriteThroughCache() if self.config.enable_cache else None

        self._sequence_number = 0
        self._timestamp_counter = 0
        self._last_compaction_check = time.time()
        self._stats = {
            "get_count": 0,
            "set_count": 0,
            "delete_count": 0,
            "compactions": 0,
            "flushes": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

        self._recover_from_wal()

    def _recover_from_wal(self) -> None:
        """Recover database state from Write-Ahead Log after a crash.

        Replays all WAL entries to restore the database to its last consistent state
        before a shutdown or crash.
        """
        try:
            entries = self.wal.recover()
            for key, value, timestamp, deleted in entries:
                self.memtable.put(key, value, timestamp, deleted)
        except Exception:
            pass

    def _validate_key(self, key: str) -> None:
        """Validate that a key meets requirements.

        Args:
            key: The key to validate

        Raises:
            InvalidKeyError: If key is not a string, is empty, or exceeds size limit

        """
        if not isinstance(key, str):
            raise InvalidKeyError("Key must be a string")
        if len(key) == 0:
            raise InvalidKeyError("Key cannot be empty")
        if len(key) > 1024:
            raise InvalidKeyError("Key cannot exceed 1024 bytes")

    def _validate_value(self, value: bytes) -> None:
        """Validate that a value meets requirements.

        Args:
            value: The value to validate

        Raises:
            InvalidValueError: If value is not bytes or exceeds size limit

        """
        if not isinstance(value, bytes):
            raise InvalidValueError("Value must be bytes")
        if len(value) > 512 * 1024 * 1024:
            raise InvalidValueError("Value cannot exceed 512MB")

    def _get_timestamp(self) -> int:
        """Generate a unique timestamp for a write operation.

        Returns:
            A unique timestamp in microseconds with sequence number to ensure
            uniqueness even for operations in the same microsecond.

        """
        with self._lock:
            self._timestamp_counter += 1
            return int(time.time() * 1000000) + self._timestamp_counter

    def _flush_memtables(self) -> None:
        """Flush all full memtables to disk as SSTables.

        Used when concurrent memtables are enabled. Flushes all full memtables
        while keeping active ones in memory.

        Raises:
            Exception: If flushing fails

        """
        try:
            if isinstance(self.memtable, ConcurrentMemtables):
                full_memtables = self.memtable.get_full_memtables()

                for index, memtable in full_memtables:
                    if memtable.get_count() == 0:
                        continue

                    sstable_path = self.data_directory / SSTable.create_filename(
                        self._sequence_number, 0
                    )
                    self._sequence_number += 1

                    sstable = SSTable(sstable_path, level=0, is_new=True)

                    entries = memtable.get_sorted_entries()
                    for key, entry in entries:
                        sstable.write_record(
                            key, entry.value, entry.timestamp, entry.deleted, compress=True
                        )

                    sstable.finalize()
                    self.compactor.add_sstable(sstable, level=0)
                    self.memtable.clear_memtable(index)

                self.wal.rotate()
                self._stats["flushes"] += 1

        except Exception:
            raise

    def _flush_memtable(self) -> None:
        """Flush the current memtable to disk as an SSTable.

        Used when concurrent memtables are disabled. Writes all entries from
        the memtable to a new SSTable file and clears the memtable.

        Raises:
            Exception: If flushing fails

        """
        try:
            if self.memtable.get_count() == 0:
                return

            sstable_path = self.data_directory / SSTable.create_filename(self._sequence_number, 0)
            self._sequence_number += 1

            sstable = SSTable(sstable_path, level=0, is_new=True)

            entries = self.memtable.get_sorted_entries()
            for key, entry in entries:
                sstable.write_record(
                    key, entry.value, entry.timestamp, entry.deleted, compress=True
                )

            sstable.finalize()
            self.compactor.add_sstable(sstable, level=0)
            self.memtable.clear()
            self.wal.rotate()
            self._stats["flushes"] += 1

        except Exception:
            raise

    def _check_compaction(self) -> None:
        """Check if compaction is needed and trigger if necessary.

        Called periodically to check if the number of SSTables exceeds the threshold
        and trigger background compaction if needed.
        """
        if self.compactor.needs_compaction():
            self._perform_compaction()

    def _perform_compaction(self) -> None:
        """Perform database compaction to optimize storage and read performance.

        Compaction merges overlapping SSTables, removes deleted entries, and
        reorganizes the LSM-tree structure. Uses non-blocking lock to avoid
        contention with concurrent operations.
        """
        if not self._compaction_lock.acquire(blocking=False):
            return

        try:
            range_to_compact = self.compactor.select_compaction_range()
            if range_to_compact:
                from_level, to_level = range_to_compact
                self.compactor.compact_levels(from_level, to_level)
                self._stats["compactions"] += 1

        except Exception:
            pass

        finally:
            self._compaction_lock.release()

    def set(self, key: str, value: bytes) -> None:
        """Store a key-value pair in the database.

        Writes the key-value pair to the write-ahead log first (for durability),
        then to the memtable. If the memtable becomes full, it is automatically
        flushed to disk as an SSTable.

        Args:
            key: String key (max 1024 bytes)
            value: Bytes value (max 512MB)

        Raises:
            DatabaseClosedError: If database is closed
            InvalidKeyError: If key is invalid
            InvalidValueError: If value is invalid
            Exception: If write operation fails

        Example:
            >>> db.set("user:123", b"John Doe")

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is closed")

            self._validate_key(key)
            self._validate_value(value)

            try:
                timestamp = self._get_timestamp()

                self.wal.write(key, value, timestamp, deleted=False)

                self.memtable.put(key, value, timestamp, deleted=False)

                if self.cache:
                    self.cache.put(key, value, timestamp, deleted=False)

                self._stats["set_count"] += 1

                if isinstance(self.memtable, ConcurrentMemtables):
                    if self.memtable.get_total_size() >= self.config.memtable_size:
                        self._flush_memtables()
                else:
                    if self.memtable.is_full():
                        self._flush_memtable()

                if time.time() - self._last_compaction_check > 10:
                    self._last_compaction_check = time.time()
                    self._check_compaction()

            except Exception:
                raise

    def get(self, key: str) -> Optional[bytes]:
        """Retrieve a value from the database by key.

        Looks up the key in order: cache, memtable, then SSTables. Returns None
        if the key doesn't exist or has been deleted.

        Args:
            key: String key to retrieve

        Returns:
            The value associated with the key, or None if not found or deleted

        Raises:
            DatabaseClosedError: If database is closed
            InvalidKeyError: If key is invalid
            Exception: If read operation fails

        Example:
            >>> value = db.get("user:123")
            >>> if value:
            ...     print(value.decode())

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is closed")

            self._validate_key(key)

            try:
                if self.cache:
                    cached = self.cache.get(key)
                    if cached:
                        value, _, deleted = cached
                        self._stats["cache_hits"] += 1
                        self._stats["get_count"] += 1
                        if deleted:
                            return None
                        return value
                    self._stats["cache_misses"] += 1

                entry = self.memtable.get(key) if isinstance(self.memtable, Memtable) else None
                if entry is None and isinstance(self.memtable, ConcurrentMemtables):
                    entry = self.memtable.get(key)

                if entry:
                    self._stats["get_count"] += 1
                    if entry.deleted:
                        return None
                    return entry.value

                result = self.compactor.search_key(key)
                if result:
                    value, timestamp, deleted = result
                    self._stats["get_count"] += 1

                    if self.cache:
                        self.cache.put(key, value, timestamp, deleted)

                    if deleted:
                        return None
                    return value

                self._stats["get_count"] += 1
                return None

            except Exception:
                raise

    def delete(self, key: str) -> None:
        """Delete a key from the database.

        Marks the key as deleted by writing a delete marker to the WAL and memtable.
        The actual data is not immediately removed but will be cleaned up during
        compaction.

        Args:
            key: String key to delete

        Raises:
            DatabaseClosedError: If database is closed
            InvalidKeyError: If key is invalid
            Exception: If delete operation fails

        Example:
            >>> db.delete("user:123")

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is closed")

            self._validate_key(key)

            try:
                timestamp = self._get_timestamp()

                self.wal.write(key, b"", timestamp, deleted=True)

                self.memtable.delete(key, timestamp)

                if self.cache:
                    self.cache.put(key, b"", timestamp, deleted=True)

                self._stats["delete_count"] += 1

                if isinstance(self.memtable, ConcurrentMemtables):
                    if self.memtable.get_total_size() >= self.config.memtable_size:
                        self._flush_memtables()
                else:
                    if self.memtable.is_full():
                        self._flush_memtable()

            except Exception:
                raise

    def flush(self) -> None:
        """Manually flush memtable to disk.

        Forces all pending data in the memtable to be written to disk as SSTables,
        ensuring durability. This is typically called before shutdown or when
        immediate persistence is required.

        Raises:
            DatabaseClosedError: If database is closed
            Exception: If flush operation fails

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is closed")

            if isinstance(self.memtable, ConcurrentMemtables):
                self._flush_memtables()
            else:
                self._flush_memtable()

    def compact(self) -> None:
        """Manually trigger database compaction.

        Initiates a compaction cycle to merge SSTables and remove deleted entries.
        Compaction runs in the background and doesn't block writes.

        Raises:
            DatabaseClosedError: If database is closed

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is closed")
            self._perform_compaction()

    def close(self) -> None:
        """Close the database and release all resources.

        Flushes any pending data to disk and closes file handles. The database
        cannot be used after calling this method.

        Raises:
            DatabaseClosedError: If database is already closed
            Exception: If close operation fails

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is already closed")

            try:
                if isinstance(self.memtable, ConcurrentMemtables):
                    self._flush_memtables()
                else:
                    self._flush_memtable()

                self.wal.close()
                self._closed = True

            except Exception:
                raise

    def destroy(self) -> None:
        """Completely remove the database and all its files.

        Closes the database and deletes all data files and directories.
        Use with caution as this operation is not recoverable.

        Raises:
            DatabaseClosedError: If database is closed
            Exception: If destroy operation fails

        """
        with self._lock:
            if self._closed:
                raise DatabaseClosedError("Database is closed")

            try:
                self.close()

                import shutil

                if self.data_directory.exists():
                    shutil.rmtree(self.data_directory)

            except Exception:
                raise

    def stats(self) -> Dict[str, Any]:
        """Get comprehensive database statistics.

        Returns detailed statistics about database operations, memory usage,
        storage, cache performance, and compaction state.

        Returns:
            Dictionary containing:
            - stats: Operation counts (get, set, delete, compactions, flushes, cache hits/misses)
            - wal: Write-ahead log statistics (entries, size)
            - memtable: Memtable statistics (entries, size)
            - cache: Cache statistics (entries, size)
            - compactor: Compaction statistics (SSTables per level, etc.)

        Example:
            >>> stats = db.stats()
            >>> print(f"Get operations: {stats['stats']['get_count']}")

        """
        with self._lock:
            compactor_stats = self.compactor.get_stats()

            if isinstance(self.memtable, ConcurrentMemtables):
                memtable_size = self.memtable.get_total_size()
                memtable_entries = sum(memtable.get_count() for memtable in self.memtable.memtables)
            else:
                memtable_size = self.memtable.get_size()
                memtable_entries = self.memtable.get_count()

            return {
                "stats": self._stats,
                "wal": {
                    "entries": self.wal.get_entry_count(),
                    "size": self.wal.get_size(),
                },
                "memtable": {
                    "entries": memtable_entries,
                    "size": memtable_size,
                },
                "cache": {
                    "entries": self.cache.get_count() if self.cache else 0,
                    "size": self.cache.get_size() if self.cache else 0,
                },
                "compactor": compactor_stats,
            }

    def is_closed(self) -> bool:
        """Check if the database is closed.

        Returns:
            True if the database has been closed, False otherwise

        """
        return self._closed

    def clear_key_cache(self) -> None:
        """Clear the serializer's key cache.

        The key serializer maintains a cache for performance. This method clears
        that cache in case of memory issues.
        """
        Serializer.clear_key_cache()

    def scan(self, start_key: Optional[str] = None) -> DatabaseIterator:
        """Scan all entries in the database in sorted key order.

        Iterates through all key-value pairs from an optional start key onwards.
        Results are returned in sorted order.

        Args:
            start_key: Optional starting key. If provided, iteration begins from this key.
                      If None, starts from the beginning.

        Returns:
            DatabaseIterator instance for iterating over entries

        Raises:
            DatabaseClosedError: If database is closed

        Example:
            >>> for key, value in db.scan():
            ...     print(f"{key}: {value}")

            >>> for key, value in db.scan(start_key="user:100"):
            ...     print(f"{key}: {value}")

        """
        if self._closed:
            raise DatabaseClosedError("Database is closed")
        return DatabaseIterator(self.memtable, self.compactor, start_key)

    def range(self, start_key: str, end_key: str) -> RangeIterator:
        """Query entries within a key range (inclusive on both ends).

        Iterates through all key-value pairs between start_key and end_key,
        inclusive on both boundaries. Results are returned in sorted order.

        Args:
            start_key: The starting key (inclusive)
            end_key: The ending key (inclusive)

        Returns:
            RangeIterator instance for iterating over entries in the range

        Raises:
            DatabaseClosedError: If database is closed

        Example:
            >>> for key, value in db.range("user:100", "user:200"):
            ...     print(f"{key}: {value}")

        """
        if self._closed:
            raise DatabaseClosedError("Database is closed")
        return RangeIterator(self.memtable, self.compactor, start_key, end_key)

    def __enter__(self):
        """Context manager entry.

        Returns:
            self: The database instance

        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit that ensures database is closed.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        """
        if not self._closed:
            self.close()

    def __repr__(self) -> str:
        """Get string representation of the database.

        Returns:
            String representation showing closed status

        """
        return f"YellowDB(closed={self._closed})"
