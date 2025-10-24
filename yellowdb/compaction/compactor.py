"""YellowDB Compaction and LSM-Tree Management module.

Provides compaction strategies and level management for the LSM-tree architecture.
The compactor merges SSTables across levels to reduce read amplification and
reclaim space from deleted entries. Supports both tiered and leveled compaction strategies.
"""

import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..storage.sstable import SSTable
from ..utils.config import Config
from ..utils.exceptions import CompactionError


class Level:
    """Represents a single level in the LSM-tree hierarchy.

    Each level contains a collection of SSTables that are merged during compaction.
    Lower levels (0) contain newer data, while higher levels contain older, more
    compacted data. Thread-safe for concurrent access.

    Attributes:
        data_directory: Directory where SSTables are stored
        level_number: Level number (0 = newest)
        sstables: List of SSTables in this level, maintained in sorted order

    Thread Safety:
        All public methods are protected by an RLock for thread-safe operations.

    """

    def __init__(self, data_directory: Path, level_number: int):
        """Initialize a level in the LSM-tree.

        Args:
            data_directory: Directory where SSTables are stored
            level_number: Level number in the hierarchy (0 = newest)

        """
        self.data_directory = data_directory
        self.level_number = level_number
        self.sstables: List[SSTable] = []

        self._lock = threading.RLock()

    def add_sstable(self, sstable: SSTable) -> None:
        """Add an SSTable to this level and maintain sorted order.

        Args:
            sstable: SSTable to add to this level

        Thread Safety:
            This method is thread-safe.

        """
        with self._lock:
            self.sstables.append(sstable)
            self.sstables.sort(key=lambda x: x.get_minimum_key() or "")

    def get_sstables(self) -> List[SSTable]:
        """Get a copy of all SSTables in this level.

        Returns:
            List of SSTables in sorted order by minimum key

        Thread Safety:
            This method is thread-safe and returns a copy.

        """
        with self._lock:
            return list(self.sstables)

    def remove_sstable(self, sstable: SSTable) -> None:
        """Remove an SSTable from this level.

        Args:
            sstable: SSTable to remove

        Thread Safety:
            This method is thread-safe.

        """
        with self._lock:
            if sstable in self.sstables:
                self.sstables.remove(sstable)

    def get_sstables_for_range(self, start_key: str, end_key: str) -> List[SSTable]:
        """Get SSTables that may contain keys in the specified range.

        Uses key range metadata to filter SSTables without scanning their contents.

        Args:
            start_key: Starting key (inclusive)
            end_key: Ending key (inclusive)

        Returns:
            List of SSTables whose key ranges overlap with the query range

        Thread Safety:
            This method is thread-safe.

        """
        with self._lock:
            relevant = []
            for sstable in self.sstables:
                minimum_key, maximum_key = sstable.get_key_range()

                if maximum_key and maximum_key < start_key:
                    continue
                if minimum_key and minimum_key > end_key:
                    continue

                relevant.append(sstable)

            return relevant

    def get_size(self) -> int:
        """Get the total size of all SSTables in this level.

        Returns:
            Total size in bytes

        Thread Safety:
            This method is thread-safe.

        """
        with self._lock:
            return sum(sstable.get_file_size() for sstable in self.sstables)

    def __len__(self) -> int:
        """Get the number of SSTables in this level.

        Returns:
            Number of SSTables

        """
        return len(self.sstables)


class Compactor:
    """Manages compaction and level organization for the LSM-tree.

    The Compactor coordinates the merging of SSTables across levels to reduce
    read amplification and reclaim space. It supports both tiered and leveled
    compaction strategies, automatically triggering compaction when levels exceed
    their size thresholds.

    Attributes:
        data_directory: Directory where SSTables are stored
        levels: Dictionary mapping level numbers to Level instances
        config: Configuration instance for compaction parameters

    Thread Safety:
        The Compactor is thread-safe for concurrent reads and writes. Compaction
        operations use a separate lock to prevent multiple simultaneous compactions.

    Example:
        >>> compactor = Compactor(Path("/data"))
        >>> compactor.add_sstable(sstable, level=0)
        >>> if compactor.needs_compaction():
        ...     range = compactor.select_compaction_range()
        ...     if range:
        ...         compactor.compact_levels(range[0], range[1])

    """

    def __init__(self, data_directory: Path):
        """Initialize the compactor.

        Args:
            data_directory: Directory where SSTables are stored

        """
        self.config = Config()
        self.data_directory = Path(data_directory)
        self.levels: Dict[int, Level] = {}

        self._lock = threading.RLock()
        self._compaction_lock = threading.Lock()
        self._next_sequence = 0

        self._initialize_levels()

    def _initialize_levels(self) -> None:
        """Initialize all levels in the LSM-tree hierarchy.

        Creates 10 levels by default to support deep LSM-trees.
        """
        maximum_levels = 10
        for i in range(maximum_levels):
            self.levels[i] = Level(self.data_directory, i)

    def add_sstable(self, sstable: SSTable, level: int = 0) -> None:
        """Add an SSTable to a specific level.

        Args:
            sstable: SSTable to add
            level: Level number to add to (default: 0)

        Thread Safety:
            This method is thread-safe.

        """
        with self._lock:
            if level not in self.levels:
                self.levels[level] = Level(self.data_directory, level)
            self.levels[level].add_sstable(sstable)

    def get_level(self, level: int) -> Level:
        """Get a specific level, creating it if necessary.

        Args:
            level: Level number to retrieve

        Returns:
            Level instance

        Thread Safety:
            This method is thread-safe.

        """
        with self._lock:
            if level not in self.levels:
                self.levels[level] = Level(self.data_directory, level)
            return self.levels[level]

    def needs_compaction(self) -> bool:
        """Check if any level needs compaction.

        Compaction is needed when Level 0 has more than 2 SSTables or when
        any level exceeds its size threshold based on the compaction strategy.

        Returns:
            True if compaction is needed, False otherwise

        Thread Safety:
            This method is thread-safe.

        Note:
            The tiered strategy uses exponential growth (4^level), while the
            leveled strategy uses slower growth (2^(level-1)).

        """
        with self._lock:
            level_0 = self.get_level(0)
            if len(level_0) > 2:
                return True

            for i in range(1, self.config.compaction_threshold):
                level = self.get_level(i)

                if self.config.compaction_strategy == "tiered":
                    tier_multiplier = 4**i
                else:
                    tier_multiplier = 2 ** (i - 1)

                maximum_level_size = self.config.sstable_size * tier_multiplier
                level_size = level.get_size()

                if level_size > maximum_level_size:
                    return True

            return False

    def select_compaction_range(self) -> Optional[Tuple[int, int]]:
        """Select which levels to compact.

        Scans levels from 0 upward to find the first level that exceeds its
        threshold, returning a tuple of (source_level, destination_level).

        Returns:
            Tuple of (from_level, to_level) if compaction needed, None otherwise

        Thread Safety:
            This method is thread-safe.

        Example:
            >>> range = compactor.select_compaction_range()
            >>> if range:
            ...     compactor.compact_levels(range[0], range[1])

        """
        with self._lock:
            for i in range(self.config.compaction_threshold - 1):
                level = self.get_level(i)

                if i == 0:
                    if len(level) > 2:
                        return (i, i + 1)
                else:
                    if self.config.compaction_strategy == "tiered":
                        tier_multiplier = 4**i
                    else:
                        tier_multiplier = 2 ** (i - 1)

                    maximum_level_size = self.config.sstable_size * tier_multiplier
                    level_size = level.get_size()

                    if level_size > maximum_level_size:
                        return (i, i + 1)

            return None

    def compact_levels(self, from_level: int, to_level: int) -> None:
        """Compact SSTables from one level to the next.

        Merges all SSTables from the source level with destination level SSTables,
        resolving conflicts by timestamp (newer wins). Creates a new merged SSTable
        in the destination level and removes old SSTables.

        Args:
            from_level: Source level number
            to_level: Destination level number

        Raises:
            CompactionError: If compaction fails

        Thread Safety:
            Uses internal locking to safely update level membership.

        Note:
            Entries are sorted by key and compressed during the merge process.
            Deletion markers are preserved during compaction.

        """
        try:
            source_level = self.get_level(from_level)
            destination_level = self.get_level(to_level)

            source_sstables = source_level.get_sstables()
            destination_sstables = destination_level.get_sstables()

            if not source_sstables:
                return

            merged_entries: Dict[str, Tuple[bytes, int, bool]] = {}

            for sstable in source_sstables:
                for key, value, timestamp, deleted in sstable.scan_all():
                    if key not in merged_entries or merged_entries[key][1] < timestamp:
                        merged_entries[key] = (value, timestamp, deleted)

            for sstable in destination_sstables:
                for key, value, timestamp, deleted in sstable.scan_all():
                    if key not in merged_entries:
                        merged_entries[key] = (value, timestamp, deleted)

            new_sstable_path = self.data_directory / SSTable.create_filename(
                self._next_sequence, to_level
            )
            self._next_sequence += 1

            new_sstable = SSTable(new_sstable_path, level=to_level, is_new=True)

            sorted_keys = sorted(merged_entries.keys())
            for key in sorted_keys:
                value, timestamp, deleted = merged_entries[key]
                new_sstable.write_record(key, value, timestamp, deleted, compress=True)

            new_sstable.finalize()

            with self._lock:
                for sstable in source_sstables:
                    source_level.remove_sstable(sstable)
                    sstable.delete()

                destination_level.add_sstable(new_sstable)

        except Exception as e:
            raise CompactionError(f"Compaction failed: {e}") from e

    def search_key(self, key: str) -> Optional[Tuple[bytes, int, bool]]:
        """Search for a key across all levels.

        Searches from Level 0 (newest) downward, returning the first match found.
        This ensures the most recent version of the key is returned.

        Args:
            key: The key to search for

        Returns:
            Tuple of (value, timestamp, deleted) if found, None otherwise

        Thread Safety:
            This method is thread-safe.

        Example:
            >>> result = compactor.search_key("user:123")
            >>> if result:
            ...     value, ts, deleted = result

        """
        with self._lock:
            for level_number in range(self.config.compaction_threshold):
                level = self.get_level(level_number)
                for sstable in level.get_sstables():
                    result = sstable.get(key)
                    if result:
                        return result

            return None

    def range_search(self, start_key: str, end_key: str) -> Dict[str, Tuple[bytes, int, bool]]:
        """Search for all keys within a range across all levels.

        Queries all levels for keys in the specified range, merging results with
        level precedence (Level 0 values override deeper levels).

        Args:
            start_key: Starting key (inclusive)
            end_key: Ending key (inclusive)

        Returns:
            Dictionary mapping keys to (value, timestamp, deleted) tuples

        Thread Safety:
            This method is thread-safe.

        Example:
            >>> results = compactor.range_search("user:100", "user:200")
            >>> for key, (value, ts, deleted) in results.items():
            ...     print(f"{key}: {value}")

        """
        results = {}

        with self._lock:
            for level_number in range(self.config.compaction_threshold):
                level = self.get_level(level_number)

                relevant_sstables = level.get_sstables_for_range(start_key, end_key)

                for sstable in relevant_sstables:
                    for key, value, timestamp, deleted in sstable.range_query(start_key, end_key):
                        if key not in results:
                            results[key] = (value, timestamp, deleted)

        return results

    def get_stats(self) -> Dict:
        """Get statistics about the compactor and its levels.

        Returns:
            Dictionary containing:
                - total_size: Total size of all SSTables across levels
                - levels: Per-level stats (sstable count and size)
                - needs_compaction: Whether compaction is needed
                - strategy: Current compaction strategy

        Thread Safety:
            This method is thread-safe.

        Example:
            >>> stats = compactor.get_stats()
            >>> print(f"Total size: {stats['total_size']} bytes")
            >>> print(f"Needs compaction: {stats['needs_compaction']}")

        """
        with self._lock:
            stats = {
                "total_size": 0,
                "levels": {},
                "needs_compaction": self.needs_compaction(),
                "strategy": self.config.compaction_strategy,
            }

            for level_number in range(self.config.compaction_threshold):
                level = self.get_level(level_number)
                size = level.get_size()
                stats["total_size"] += size
                stats["levels"][level_number] = {"sstables": len(level), "size": size}

            return stats

    def __repr__(self) -> str:
        """Get string representation of the Compactor.

        Returns:
            String showing number of levels and total SSTables

        """
        total_sstables = sum(len(self.get_level(i)) for i in self.levels)
        return f"Compactor(levels={len(self.levels)}, sstables={total_sstables})"
