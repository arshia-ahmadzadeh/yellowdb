"""YellowDB sparse indexing module.

Provides sparse indexing for SSTables to enable efficient key lookups
without scanning the entire file. Uses bloom filters for probabilistic
key existence checking.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..core.bloom_filter import BloomFilter
from ..utils.config import Config
from ..utils.exceptions import SerializationError


class SparseIndex:
    """Sparse index for efficient SSTable key lookups.

    Maintains a sample of keys from an SSTable along with their file offsets,
    allowing binary search to quickly locate approximate positions. Optionally
    uses a bloom filter to quickly eliminate keys that don't exist in the SSTable.

    Attributes:
        _keys: Dictionary mapping keys to file offsets
        _sorted_keys: Sorted list of keys for binary search
        _bloom_filter: Optional bloom filter for key existence checks
        config: Configuration instance

    Example:
        >>> index = SparseIndex()
        >>> index.add_key("user:100", offset=1024)
        >>> offset = index.get_offset("user:100")
        >>> index.save(Path("index.json"))

    """

    def __init__(self):
        """Initialize the index."""
        self.config = Config()

        self._keys: Dict[str, int] = {}
        self._sorted_keys: List[str] = []
        self._bloom_filter: Optional[BloomFilter] = None

        if self.config.enable_bloom_filter:
            self._bloom_filter = BloomFilter()

    def add_key(self, key: str, offset: int) -> None:
        """Add a key and its file offset to the index.

        Args:
            key: The key to index
            offset: The byte offset of this key in the SSTable file

        """
        self._keys[key] = offset
        if key not in self._sorted_keys:
            self._sorted_keys.append(key)
            self._sorted_keys.sort()

        if self._bloom_filter:
            self._bloom_filter.add(key)

    def get_offset(self, key: str) -> Optional[int]:
        """Get the approximate offset for a key using binary search.

        Returns the offset of the key, or the offset of the largest key less
        than the search key for keys not exactly in the index.

        Args:
            key: The key to look up

        Returns:
            File offset or None if key might not exist (bloom filter check)

        """
        if not self.might_contain(key):
            return None

        if not self._sorted_keys:
            return 0

        left, right = 0, len(self._sorted_keys) - 1
        result_offset = 0

        while left <= right:
            middle = (left + right) // 2
            middle_key = self._sorted_keys[middle]

            if middle_key <= key:
                result_offset = self._keys[middle_key]
                left = middle + 1
            else:
                right = middle - 1

        return result_offset

    def might_contain(self, key: str) -> bool:
        """Check if a key might exist in the SSTable using bloom filter.

        Args:
            key: The key to check

        Returns:
            True if key might exist, False if it definitely doesn't exist

        """
        if not self._bloom_filter:
            return True
        return self._bloom_filter.might_exist(key)

    def get_key_range(self, start_key: str, end_key: str) -> tuple:
        """Get file offsets for a range of keys.

        Returns the byte offsets marking the approximate range in the file
        where keys between start_key and end_key might be located.

        Args:
            start_key: Starting key of the range (inclusive)
            end_key: Ending key of the range (inclusive)

        Returns:
            Tuple of (start_offset, end_offset)

        """
        if not self._sorted_keys:
            return 0, 0

        start_index = 0
        for i, key in enumerate(self._sorted_keys):
            if key >= start_key:
                start_index = i
                break

        end_index = len(self._sorted_keys) - 1
        for i, key in enumerate(self._sorted_keys):
            if key > end_key:
                end_index = i - 1
                break

        start_offset = (
            self._keys.get(self._sorted_keys[start_index], 0)
            if start_index < len(self._sorted_keys)
            else 0
        )
        end_offset = self._keys.get(self._sorted_keys[end_index], 0) if end_index >= 0 else 0

        return start_offset, end_offset

    def save(self, path: Path) -> None:
        """Save the index to a JSON file.

        Serializes the keys and bloom filter to disk for persistence.

        Args:
            path: Path where index should be saved

        Raises:
            SerializationError: If serialization fails

        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "keys": self._keys,
                "bloom_filter": self._bloom_filter.to_bytes().hex() if self._bloom_filter else None,
            }

            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            raise SerializationError(f"Failed to save index: {e}") from e

    def load(self, path: Path) -> None:
        """Load the index from a JSON file.

        Deserializes the keys and bloom filter from disk.

        Args:
            path: Path to the index file to load

        Raises:
            SerializationError: If deserialization fails

        """
        try:
            if path.exists():
                with open(path) as f:
                    data = json.load(f)

                self._keys = data.get("keys", {})
                self._sorted_keys = sorted(self._keys.keys())

                if self.config.enable_bloom_filter and data.get("bloom_filter"):
                    bf_bytes = bytes.fromhex(data["bloom_filter"])
                    self._bloom_filter = BloomFilter.from_bytes(bf_bytes)
        except Exception as e:
            raise SerializationError(f"Failed to load index: {e}") from e

    def clear(self) -> None:
        """Clear all entries from the index.

        Resets the index to empty state with fresh bloom filter if enabled.
        """
        self._keys.clear()
        self._sorted_keys.clear()
        if self._bloom_filter:
            self._bloom_filter = BloomFilter()

    def __len__(self) -> int:
        """Get the number of indexed keys.

        Returns:
            Number of keys in the index

        """
        return len(self._keys)

    def __repr__(self) -> str:
        """Get string representation of the index.

        Returns:
            String showing entry count and bloom filter status

        """
        return (
            f"SparseIndex(entries={len(self._keys)}, bloom_filter={self._bloom_filter is not None})"
        )
