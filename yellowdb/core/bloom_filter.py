"""Bloom filter implementation for YellowDB.

This module provides a space-efficient probabilistic data structure for testing
set membership. Bloom filters are used to quickly determine if a key might exist
in an SSTable without reading the entire file, reducing unnecessary disk I/O.

The implementation uses multiple hash functions (MD5-based) to achieve low false
positive rates while maintaining minimal memory overhead. False positives are
possible, but false negatives are not.

Classes:
    BloomFilter: Probabilistic set membership test with configurable size and hash count.
"""

import hashlib
from typing import List

from ..utils.config import Config


class BloomFilter:
    """Probabilistic data structure for fast set membership testing.

    A Bloom filter is a space-efficient probabilistic data structure that tests whether
    an element is a member of a set. It can return false positives (saying an element
    is in the set when it's not), but never false negatives (saying an element is not
    in the set when it is).

    The filter uses multiple hash functions and a bit array to achieve high space
    efficiency. This implementation uses MD5 hashing with different seeds to generate
    multiple independent hash functions.

    Attributes:
        size: Total number of bits in the filter.
        num_hashes: Number of hash functions to use.
        bits: Byte array storing the bit vector.

    Example:
        >>> bf = BloomFilter(size=10000, num_hashes=3)
        >>> bf.add("user:123")
        >>> bf.add("user:456")
        >>> bf.might_exist("user:123")
        True
        >>> bf.might_exist("user:999")
        False

    """

    def __init__(self, size: int = None, num_hashes: int = None):
        """Initialize a new Bloom filter.

        Args:
            size: Number of bits in the filter. If None, uses the default from config.
                Larger sizes reduce false positive rates but use more memory.
            num_hashes: Number of hash functions to use. If None, uses the default
                from config. More hash functions reduce false positives but slow down
                operations.

        Example:
            >>> bf = BloomFilter(size=10000, num_hashes=3)
            >>> bf = BloomFilter()  # Use config defaults

        """
        config = Config()
        self.size = size or config.bloom_filter_size
        self.num_hashes = num_hashes or config.bloom_filter_hash_functions

        self.bits = bytearray((self.size + 7) // 8)

    def _get_hashes(self, key: str) -> List[int]:
        """Generate multiple hash values for a key.

        Uses MD5 with different seeds (appending the hash function index) to generate
        multiple independent hash values. Each hash is reduced modulo the filter size
        to get a bit position.

        Args:
            key: The key to hash.

        Returns:
            List of bit positions (integers in range [0, size)) for this key.

        Note:
            While MD5 is not cryptographically secure, it's sufficient for Bloom
            filters where security is not a concern.

        """
        hashes = []
        key_bytes = key.encode("utf-8")

        for i in range(self.num_hashes):
            hasher = hashlib.md5()
            hasher.update(key_bytes + bytes([i]))
            hash_value = int.from_bytes(hasher.digest(), byteorder="big") % self.size
            hashes.append(hash_value)

        return hashes

    def add(self, key: str) -> None:
        """Add a key to the Bloom filter.

        Sets all bits corresponding to the hash values of this key to 1.

        Args:
            key: The key to add to the filter.

        Example:
            >>> bf = BloomFilter()
            >>> bf.add("user:123")
            >>> bf.add("product:456")

        """
        for hash_value in self._get_hashes(key):
            byte_index = hash_value // 8
            bit_index = hash_value % 8
            self.bits[byte_index] |= 1 << bit_index

    def might_exist(self, key: str) -> bool:
        """Check if a key might exist in the set.

        Returns True if the key might exist (could be a false positive), or False
        if the key definitely does not exist (never a false negative).

        Args:
            key: The key to check.

        Returns:
            True if all bits for this key's hash values are set, False if any bit
            is not set.

        Example:
            >>> bf = BloomFilter()
            >>> bf.add("user:123")
            >>> bf.might_exist("user:123")
            True
            >>> bf.might_exist("user:999")  # Probably False, but could be True
            False

        Note:
            A True result means the key might be in the set (could be false positive).
            A False result means the key is definitely not in the set.

        """
        for hash_value in self._get_hashes(key):
            byte_index = hash_value // 8
            bit_index = hash_value % 8
            if not (self.bits[byte_index] & (1 << bit_index)):
                return False
        return True

    def to_bytes(self) -> bytes:
        """Serialize the Bloom filter to bytes for storage.

        Returns:
            Byte representation of the bit array.

        Example:
            >>> bf = BloomFilter()
            >>> bf.add("key1")
            >>> serialized = bf.to_bytes()
            >>> with open("filter.bloom", "wb") as f:
            ...     f.write(serialized)

        """
        return bytes(self.bits)

    @classmethod
    def from_bytes(cls, data: bytes, num_hashes: int = None) -> "BloomFilter":
        """Deserialize a Bloom filter from bytes.

        Args:
            data: Serialized Bloom filter bytes (the bit array).
            num_hashes: Number of hash functions used. If None, uses config default.

        Returns:
            A new BloomFilter instance with the deserialized state.

        Example:
            >>> with open("filter.bloom", "rb") as f:
            ...     data = f.read()
            >>> bf = BloomFilter.from_bytes(data, num_hashes=3)
            >>> bf.might_exist("key1")
            True

        """
        config = Config()
        num_hashes = num_hashes or config.bloom_filter_hash_functions

        bf = cls(size=len(data) * 8, num_hashes=num_hashes)
        bf.bits = bytearray(data)
        return bf

    def __len__(self) -> int:
        """Get the size of the bit array in bytes.

        Returns:
            Number of bytes used to store the bit array.

        """
        return len(self.bits)

    def get_false_positive_rate(self, num_elements: int) -> float:
        """Calculate the expected false positive rate.

        Uses the standard Bloom filter formula: (1 - e^(-kn/m))^k
        where k is the number of hash functions, n is the number of elements,
        and m is the size of the bit array.

        Args:
            num_elements: The number of elements that have been (or will be) added
                to the filter.

        Returns:
            The expected false positive rate as a float between 0 and 1.

        Example:
            >>> bf = BloomFilter(size=10000, num_hashes=3)
            >>> for i in range(100):
            ...     bf.add(f"key{i}")
            >>> fpr = bf.get_false_positive_rate(100)
            >>> print(f"False positive rate: {fpr:.4f}")
            False positive rate: 0.0045

        Note:
            This is a theoretical estimate based on the assumption of perfect hash
            function independence. Actual false positive rates may vary slightly.

        """
        import math

        k = self.num_hashes
        m = self.size
        n = num_elements
        return (1 - math.exp(-k * n / m)) ** k
