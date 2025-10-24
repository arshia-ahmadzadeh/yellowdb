"""YellowDB iterator module for scanning database entries.

Provides iterator classes for scanning all database entries or querying
entries within a specific key range. Iterators merge results from memtable
and SSTables in sorted order.
"""

from typing import List, Optional, Tuple

from ..compaction.compactor import Compactor
from ..storage.memtable import ConcurrentMemtables


class DatabaseIterator:
    """Iterator for scanning all entries in the database in sorted key order.

    Iterates through all key-value pairs, optionally starting from a specific key.
    Results are returned in sorted order and reflect the current state of the
    database, including entries from memtable and all SSTables.

    Attributes:
        memtable_source: Reference to the memtable(s)
        compactor: Reference to the compactor/SSTable manager
        start_key: Optional key to start iteration from
        _entries: List of (key, value) tuples after loading
        _current_index: Current position in the iteration

    Example:
        Iterate through all entries:

        >>> for key, value in db.scan():
        ...     print(f"{key}: {value}")

        Start from a specific key:

        >>> for key, value in db.scan(start_key="user:100"):
        ...     print(f"{key}: {value}")

        Count total entries:

        >>> iterator = db.scan()
        >>> count = iterator.count()

    """

    def __init__(self, memtable_source, compactor: Compactor, start_key: Optional[str] = None):
        """Initialize a database iterator.

        Args:
            memtable_source: Memtable or ConcurrentMemtables instance
            compactor: Compactor instance managing SSTables
            start_key: Optional key to start iteration from (inclusive)

        Note:
            Iterator loads all matching entries into memory, so it may use
            significant memory for very large databases.

        """
        self.memtable_source = memtable_source
        self.compactor = compactor
        self.start_key = start_key

        self._entries: List[Tuple[str, bytes]] = []
        self._current_index = 0

        self._load_entries()

    def _load_entries(self) -> None:
        """Load and merge entries from memtable and all SSTables.

        Merges entries from the in-memory memtable and all on-disk SSTables,
        keeping the most recent version of each key (based on timestamp),
        and excluding deleted entries.
        """
        if isinstance(self.memtable_source, ConcurrentMemtables):
            memtable_data = self.memtable_source.get_all_entries()
        else:
            memtable_data = self.memtable_source.get_all()

        memtable_entries = [
            (key, entry.value, entry.timestamp, entry.deleted)
            for key, entry in memtable_data.items()
            if self.start_key is None or key >= self.start_key
        ]

        all_entries = {}
        for level_number in range(10):
            level = self.compactor.get_level(level_number)
            for sstable in level.get_sstables():
                for key, value, timestamp, deleted in sstable.scan_all():
                    if (self.start_key is None or key >= self.start_key) and (
                        key not in all_entries or all_entries[key][1] < timestamp
                    ):
                        all_entries[key] = (value, timestamp, deleted)

        merged = {}

        for entry in all_entries.items():
            merged[entry[0]] = entry[1]

        for key, value, timestamp, deleted in memtable_entries:
            merged[key] = (value, timestamp, deleted)

        self._entries = [
            (key, value)
            for key, (value, timestamp, deleted) in sorted(merged.items())
            if not deleted
        ]

    def __iter__(self) -> "DatabaseIterator":
        """Reset iterator to beginning for a new iteration.

        Returns:
            self: The iterator instance

        Example:
            >>> iterator = db.scan()
            >>> for key, value in iterator:
            ...     print(key)
            >>> for key, value in iterator:  # Iterate again from start
            ...     print(key)

        """
        self._current_index = 0
        return self

    def __next__(self) -> Tuple[str, bytes]:
        """Get the next entry in the iteration.

        Returns:
            Tuple of (key, value) for the next entry

        Raises:
            StopIteration: When iteration is complete

        """
        if self._current_index >= len(self._entries):
            raise StopIteration

        result = self._entries[self._current_index]
        self._current_index += 1
        return result

    def count(self) -> int:
        """Get the total number of entries that will be iterated.

        Returns:
            Total number of entries matching the iteration criteria

        """
        return len(self._entries)

    def reset(self) -> None:
        """Reset the iterator to the beginning without reloading entries.

        Allows re-iterating through the same set of entries without
        querying the database again.
        """
        self._current_index = 0


class RangeIterator:
    """Iterator for querying entries within a key range.

    Iterates through all key-value pairs where the key falls within a
    specified range (inclusive on both ends). Results are returned in
    sorted order.

    Attributes:
        memtable_source: Reference to the memtable(s)
        compactor: Reference to the compactor/SSTable manager
        start_key: Starting key of the range (inclusive)
        end_key: Ending key of the range (inclusive)
        _entries: List of (key, value) tuples after loading
        _current_index: Current position in the iteration

    Example:
        Query a range of entries:

        >>> for key, value in db.range("user:100", "user:199"):
        ...     print(f"{key}: {value}")

        Count entries in range:

        >>> iterator = db.range("a", "z")
        >>> print(f"Entries: {iterator.count()}")

    """

    def __init__(self, memtable_source, compactor: Compactor, start_key: str, end_key: str):
        """Initialize a range iterator.

        Args:
            memtable_source: Memtable or ConcurrentMemtables instance
            compactor: Compactor instance managing SSTables
            start_key: Starting key of the range (inclusive)
            end_key: Ending key of the range (inclusive)

        Note:
            start_key must be <= end_key for meaningful results.

        """
        self.memtable_source = memtable_source
        self.compactor = compactor
        self.start_key = start_key
        self.end_key = end_key

        self._entries: List[Tuple[str, bytes]] = []
        self._current_index = 0

        self._load_entries()

    def _load_entries(self) -> None:
        """Load and merge entries from memtable and SSTables within the range.

        Merges entries from the in-memory memtable and all on-disk SSTables
        that fall within the specified key range, keeping the most recent
        version of each key and excluding deleted entries.
        """
        entries_dict = {}

        if isinstance(self.memtable_source, ConcurrentMemtables):
            memtable_data = self.memtable_source.get_all_entries()
            memtable_entries = [
                (key, entry.value, entry.timestamp, entry.deleted)
                for key, entry in memtable_data.items()
            ]
        else:
            memtable_entries = self.memtable_source.range_query(self.start_key, self.end_key)
            memtable_entries = [
                (entry.key, entry.value, entry.timestamp, entry.deleted)
                for entry in memtable_entries
            ]

        for key, value, timestamp, deleted in memtable_entries:
            if self.start_key <= key <= self.end_key and key not in entries_dict:
                entries_dict[key] = (value, timestamp, deleted)

        sstable_results = self.compactor.range_search(self.start_key, self.end_key)
        for key, (value, timestamp, deleted) in sstable_results.items():
            if key not in entries_dict:
                entries_dict[key] = (value, timestamp, deleted)

        self._entries = [
            (key, value)
            for key, (value, timestamp, deleted) in sorted(entries_dict.items())
            if not deleted
        ]

    def __iter__(self) -> "RangeIterator":
        """Reset iterator to beginning for a new iteration.

        Returns:
            self: The iterator instance

        Example:
            >>> iterator = db.range("a", "z")
            >>> for key, value in iterator:
            ...     print(key)
            >>> for key, value in iterator:  # Iterate again from start
            ...     print(key)

        """
        self._current_index = 0
        return self

    def __next__(self) -> Tuple[str, bytes]:
        """Get the next entry in the iteration.

        Returns:
            Tuple of (key, value) for the next entry

        Raises:
            StopIteration: When iteration is complete

        """
        if self._current_index >= len(self._entries):
            raise StopIteration

        result = self._entries[self._current_index]
        self._current_index += 1
        return result

    def reset(self) -> None:
        """Reset the iterator to the beginning without reloading entries.

        Allows re-iterating through the same set of entries without
        querying the database again.
        """
        self._current_index = 0

    def count(self) -> int:
        """Get the total number of entries in the range.

        Returns:
            Total number of entries within the specified key range

        """
        return len(self._entries)
