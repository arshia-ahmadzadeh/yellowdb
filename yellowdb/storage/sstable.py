"""YellowDB Sorted String Table (SSTable) module.

Provides immutable on-disk sorted tables for persistent storage of key-value pairs.
SSTables are created when memtables are flushed and form the basis of the
LSM-tree architecture. They are organized into levels for efficient compaction.
"""

from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from ..core.serializer import Serializer
from ..utils.config import Config
from ..utils.exceptions import DatabaseCorruptedError
from .index import SparseIndex


class SSTable:
    """Immutable sorted table stored on disk.

    An SSTable is a sorted file of key-value pairs that acts as a persistent
    storage tier in the LSM-tree. SSTables are created by flushing memtables
    and are never modified after creation. Multiple SSTables are organized into
    levels for compaction and efficient querying.

    Each SSTable has an associated index file for fast key lookups and optional
    bloom filter for probabilistic existence checks.

    Class Attributes:
        INDEX_EXTENSION: File extension for index files (.idx)
        BLOOM_EXTENSION: File extension for bloom filters (.bloom)
        SSTABLE_EXTENSION: File extension for SSTable files (.sst)

    Attributes:
        path: Path to the SSTable file
        level: Level in LSM-tree hierarchy (0 = most recent)
        _index: SparseIndex for efficient key lookups
        _entry_count: Number of entries in the SSTable
        _file_size: Size of SSTable file in bytes
        _minimum_key: Smallest key in this SSTable
        _maximum_key: Largest key in this SSTable

    Example:
        Create new SSTable for flushing:

        >>> sstable = SSTable(Path("level_0_seq_000001.sst"), level=0, is_new=True)
        >>> sstable.write_record("key1", b"value1", timestamp=1000, compress=True)
        >>> sstable.finalize()

        Load existing SSTable:

        >>> sstable = SSTable(Path("level_0_seq_000001.sst"), level=0, is_new=False)
        >>> value, ts, deleted = sstable.get("key1")

    """

    INDEX_EXTENSION = ".idx"
    BLOOM_EXTENSION = ".bloom"
    SSTABLE_EXTENSION = ".sst"

    def __init__(self, path: Path, level: int = 0, is_new: bool = True):
        """Initialize an SSTable.

        Args:
            path: Path to the SSTable file
            level: LSM-tree level (0=newest, higher=older)
            is_new: Whether this is a new SSTable being created. If False,
                    loads index from disk.

        Example:
            >>> sstable = SSTable(Path("table.sst"), level=0, is_new=True)

        """
        self.config = Config()
        self.path = Path(path)
        self.level = level

        self._index = SparseIndex()
        self._entry_count = 0
        self._file_size = 0
        self._maximum_key = None
        self._minimum_key = None

        if is_new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._load_index()

    def _load_index(self) -> None:
        """Load the sparse index from disk for an existing SSTable.

        Called during initialization when is_new=False. Loads the index
        and metadata necessary for efficient key lookups.
        """
        try:
            index_path = self.path.with_suffix(self.INDEX_EXTENSION)
            if index_path.exists():
                self._index.load(index_path)
                self._entry_count = len(list(self._index._keys))
                self._file_size = self.path.stat().st_size if self.path.exists() else 0

        except Exception:
            pass

    @staticmethod
    def create_filename(sequence: int, level: int = 0) -> str:
        """Create a standardized SSTable filename.

        Filenames follow the format: level_<level>_seq_<sequence>.sst

        Args:
            sequence: Sequence number to make filename unique
            level: LSM-tree level (0=newest)

        Returns:
            Filename as string

        Example:
            >>> filename = SSTable.create_filename(1, level=0)
            >>> print(filename)  # level_0_seq_000001.sst

        """
        return f"level_{level}_seq_{sequence:06d}{SSTable.SSTABLE_EXTENSION}"

    def write_record(
        self, key: str, value: bytes, timestamp: int, deleted: bool = False, compress: bool = False
    ) -> None:
        """Write a key-value record to the SSTable.

        Appends a record to the SSTable file and updates the sparse index
        sampling. Called during memtable flush to convert in-memory data
        to on-disk format.

        Args:
            key: The key string
            value: The value bytes
            timestamp: Write timestamp for versioning
            deleted: Whether this is a deletion marker
            compress: Whether to compress the value

        Raises:
            DatabaseCorruptedError: If write fails

        Example:
            >>> sstable.write_record("user:1", b"Alice", timestamp=1000)

        """
        try:
            offset = self.path.stat().st_size if self.path.exists() else 0

            with open(self.path, "ab") as f:
                bytes_written = Serializer.write_record_to_file(
                    f, key, value, timestamp, deleted, compress
                )

            sparse_interval = max(1, (self.config.block_size // (len(key.encode("utf-8")) + 32)))
            if self._entry_count % sparse_interval == 0:
                self._index.add_key(key, offset)

            if self._minimum_key is None or key < self._minimum_key:
                self._minimum_key = key
            if self._maximum_key is None or key > self._maximum_key:
                self._maximum_key = key

            self._entry_count += 1
            self._file_size += bytes_written

        except Exception as e:
            raise DatabaseCorruptedError(f"Failed to write record to SSTable: {e}") from e

    def get(self, key: str) -> Optional[Tuple[bytes, int, bool]]:
        """Look up a key in the SSTable.

        Uses the sparse index for efficient searching without scanning the
        entire file. Bloom filter is checked first for existence probability.

        Args:
            key: The key to look up

        Returns:
            Tuple of (value, timestamp, deleted) if found, None otherwise

        Example:
            >>> result = sstable.get("user:1")
            >>> if result:
            ...     value, ts, deleted = result

        """
        try:
            if not self._index.might_contain(key):
                return None

            offset = self._index.get_offset(key)
            if offset is None:
                return None

            with open(self.path, "rb") as f:
                f.seek(offset)

                for _ in range(self.config.block_size):
                    try:
                        _, record_key, value, timestamp, deleted, _ = (
                            Serializer.read_record_from_file(f)
                        )

                        if record_key == key:
                            return value, timestamp, deleted
                        elif record_key > key:
                            return None

                    except Exception:
                        return None

            return None

        except Exception:
            return None

    def delete(self) -> None:
        """Delete the SSTable and associated files from disk.

        Removes the SSTable file, index file, and bloom filter file.
        Used during compaction to discard merged tables.
        """
        try:
            if self.path.exists():
                self.path.unlink()

            index_path = self.path.with_suffix(self.INDEX_EXTENSION)
            if index_path.exists():
                index_path.unlink()

            bloom_path = self.path.with_suffix(self.BLOOM_EXTENSION)
            if bloom_path.exists():
                bloom_path.unlink()

        except Exception:
            pass

    def finalize(self) -> None:
        """Finalize the SSTable for querying.

        Saves the sparse index and bloom filter to disk. Must be called
        after all records are written and before the SSTable can be queried.

        Example:
            >>> sstable = SSTable(Path("table.sst"), is_new=True)
            >>> # ... write records ...
            >>> sstable.finalize()

        """
        try:
            self._index.save(self.path.with_suffix(self.INDEX_EXTENSION))

            if self.config.enable_bloom_filter and self._index._bloom_filter:
                bloom_filter_path = self.path.with_suffix(self.BLOOM_EXTENSION)
                bloom_filter_path.write_bytes(self._index._bloom_filter.to_bytes())

        except Exception:
            pass

    def get_entry_count(self) -> int:
        """Get the number of entries in this SSTable.

        Returns:
            Number of key-value pairs

        """
        return self._entry_count

    def get_file_size(self) -> int:
        """Get the size of the SSTable file on disk in bytes.

        Returns:
            File size in bytes, or 0 if file doesn't exist

        """
        try:
            return self.path.stat().st_size if self.path.exists() else 0
        except Exception:
            return 0

    def get_minimum_key(self) -> Optional[str]:
        """Get the smallest key in this SSTable.

        Returns:
            Minimum key string, or None if empty

        """
        return self._minimum_key

    def get_maximum_key(self) -> Optional[str]:
        """Get the largest key in this SSTable.

        Returns:
            Maximum key string, or None if empty

        """
        return self._maximum_key

    def get_key_range(self) -> Tuple[Optional[str], Optional[str]]:
        """Get the key range of this SSTable.

        Returns:
            Tuple of (minimum_key, maximum_key)

        """
        return self._minimum_key, self._maximum_key

    def scan_all(self) -> Iterator[Tuple[str, bytes, int, bool]]:
        """Scan all entries in the SSTable.

        Iterates through all key-value pairs in sorted order.

        Yields:
            Tuple of (key, value, timestamp, deleted)

        Example:
            >>> for key, value, ts, deleted in sstable.scan_all():
            ...     if not deleted:
            ...         print(f"{key}: {value}")

        """
        try:
            with open(self.path, "rb") as f:
                while True:
                    try:
                        _, key, value, timestamp, deleted, _ = Serializer.read_record_from_file(f)
                        yield key, value, timestamp, deleted

                    except Exception:
                        break

        except Exception:
            pass

    def scan_all_list(self) -> List[Tuple[str, bytes, int, bool]]:
        """Scan all entries and return as a list.

        Returns:
            List of (key, value, timestamp, deleted) tuples

        """
        return list(self.scan_all())

    def range_query(self, start_key: str, end_key: str) -> List[Tuple[str, bytes, int, bool]]:
        """Query entries within a key range.

        Uses sparse index to efficiently find the starting position,
        then scans forward until the end_key is reached.

        Args:
            start_key: Starting key (inclusive)
            end_key: Ending key (inclusive)

        Returns:
            List of (key, value, timestamp, deleted) tuples in range

        Example:
            >>> results = sstable.range_query("user:100", "user:200")

        """
        try:
            results = []

            start_offset, _ = self._index.get_key_range(start_key, end_key)

            with open(self.path, "rb") as f:
                f.seek(start_offset)

                while True:
                    try:
                        _, key, value, timestamp, deleted, _ = Serializer.read_record_from_file(f)

                        if key < start_key:
                            continue
                        if key > end_key:
                            break

                        results.append((key, value, timestamp, deleted))

                    except Exception:
                        break

            return results

        except Exception:
            return []

    def __repr__(self) -> str:
        """Get string representation of the SSTable.

        Returns:
            String showing path, level, entry count, and file size

        """
        return f"SSTable(path={self.path.name}, level={self.level}, entries={self._entry_count}, size={self.get_file_size()})"
