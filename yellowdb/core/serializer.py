"""YellowDB serialization module for efficient record encoding/decoding.

Provides optimized serialization/deserialization for key-value records with:
- Struct format caching for improved performance
- Bytearray-based building for efficient memory usage
- Optional compression for large values
- Support for deletion markers (tombstones)
- Key string caching to reduce encoding overhead

Record Format:
    [key_length:4][key:variable][value_length:4][value:variable][timestamp:8][deleted:1][compressed:1]

Markers:
    - TOMBSTONE_MARKER (0x00): Indicates a deletion record
    - ACTIVE_MARKER (0x01): Indicates an active record
    - COMPRESSION_MARKER (0x02): Indicates value is compressed
"""

import struct
import zlib
from typing import Dict, Tuple

from ..utils.config import Config
from ..utils.exceptions import SerializationError

TOMBSTONE_MARKER = b"\x00"
ACTIVE_MARKER = b"\x01"
COMPRESSION_MARKER = b"\x02"


class StructCache:
    """Cache compiled struct formats for performance optimization.

    Python's struct module compiles format strings at runtime. This cache stores
    pre-compiled struct.Struct objects to avoid recompiling the same formats
    repeatedly, providing significant performance improvement.

    Attributes:
        _cache: Dictionary mapping format strings to compiled Struct objects

    Example:
        >>> cache = StructCache()
        >>> s = StructCache.get_struct(">I")  # Big-endian unsigned int
        >>> packed = s.pack(12345)

    """

    _cache: Dict[str, struct.Struct] = {}

    @classmethod
    def get_struct(cls, format_string: str) -> struct.Struct:
        """Get or create a cached struct format.

        Looks up a format string in the cache. If not found, compiles it and
        caches the result for future use.

        Args:
            format_string: Format string in struct module syntax (e.g., ">I")

        Returns:
            A compiled struct.Struct object for the given format

        Example:
            >>> s = StructCache.get_struct(">Q")  # Big-endian unsigned long long
            >>> packed = s.pack(9999999999)

        """
        if format_string not in cls._cache:
            cls._cache[format_string] = struct.Struct(format_string)
        return cls._cache[format_string]


class Serializer:
    """Optimized record serializer with caching and compression support.

    Provides efficient serialization and deserialization of key-value records
    for storage in SSTables and other components. Uses multiple optimization
    techniques including struct caching, key string caching, and selective compression.

    Features:
        - Efficient bytearray-based building
        - Cached struct formats for performance
        - Cached key encoding to reduce repeated encoding
        - Automatic compression for large values
        - Deletion marker tracking (tombstones)

    Attributes:
        MAGIC_NUMBER: Magic bytes identifying the YellowDB format version
        _STRUCT_*: Pre-compiled struct formats for common types
        _key_cache: Cache of encoded key strings to avoid repeated encoding
        _cache_size: Current size of key cache in bytes
        _max_cache_size: Maximum size before key cache eviction

    Example:
        >>> data = Serializer.serialize_record("user:1", b"Alice", 12345)
        >>> bytes_read, key, value, ts, deleted, compressed = Serializer.deserialize_record(data)

    """

    _STRUCT_KEY_LENGTH = StructCache.get_struct(">I")
    _STRUCT_VALUE_LENGTH = StructCache.get_struct(">I")
    _STRUCT_TIMESTAMP = StructCache.get_struct(">Q")

    MAGIC_NUMBER = b"YDB2"

    _key_cache: Dict[str, bytes] = {}
    _cache_size = 0
    _max_cache_size = 1024 * 1024

    @classmethod
    def get_cached_key_bytes(cls, key: str) -> bytes:
        """Get cached key bytes or encode and cache the key.

        Reduces CPU overhead by caching encoded key strings. When the cache
        reaches its size limit, new keys are encoded but not cached.

        Args:
            key: The key string to encode

        Returns:
            UTF-8 encoded key bytes (either from cache or newly encoded)

        Example:
            >>> key_bytes = Serializer.get_cached_key_bytes("user:123")
            >>> # Subsequent calls for the same key use the cached version

        """
        if key in cls._key_cache:
            return cls._key_cache[key]

        key_bytes = key.encode("utf-8")

        if cls._cache_size < cls._max_cache_size:
            cls._key_cache[key] = key_bytes
            cls._cache_size += len(key_bytes)

        return key_bytes

    @classmethod
    def serialize_record(
        cls, key: str, value: bytes, timestamp: int, deleted: bool = False, compress: bool = False
    ) -> bytes:
        """Serialize a key-value record to bytes.

        Encodes a record in the YellowDB binary format with optional compression.
        Uses bytearray for efficient memory usage and cached struct formats for
        performance. Values larger than the compression threshold are automatically
        compressed if compression is enabled.

        Args:
            key: The key string
            value: The value bytes
            timestamp: Write timestamp (microseconds since epoch)
            deleted: Whether this is a deletion marker (tombstone)
            compress: Whether to compress the value if beneficial

        Returns:
            Serialized record bytes ready for storage

        Raises:
            SerializationError: If serialization fails

        Example:
            >>> data = Serializer.serialize_record("key1", b"value1", 12345)
            >>> data = Serializer.serialize_record("key2", b"large_data", 12346, compress=True)

        """
        try:
            key_bytes = cls.get_cached_key_bytes(key)
            key_length = len(key_bytes)

            record = bytearray()
            config = Config()

            compression_flag = ACTIVE_MARKER
            if compress and len(value) > config.compression_threshold:
                try:
                    compressed_value = zlib.compress(value, config.compression_level)
                    if len(compressed_value) < len(value):
                        value = compressed_value
                        compression_flag = COMPRESSION_MARKER
                except Exception:
                    compression_flag = ACTIVE_MARKER

            value_length = len(value)
            deleted_marker = TOMBSTONE_MARKER if deleted else ACTIVE_MARKER

            record.extend(cls._STRUCT_KEY_LENGTH.pack(key_length))
            record.extend(key_bytes)
            record.extend(cls._STRUCT_VALUE_LENGTH.pack(value_length))
            record.extend(value)
            record.extend(cls._STRUCT_TIMESTAMP.pack(timestamp))
            record.extend(deleted_marker)
            record.extend(compression_flag)

            return bytes(record)

        except Exception as e:
            raise SerializationError(f"Failed to serialize record: {e}") from e

    @classmethod
    def deserialize_record(
        cls, data: bytes, offset: int = 0
    ) -> Tuple[int, str, bytes, int, bool, bool]:
        """Deserialize a key-value record from bytes.

        Decodes a record from the YellowDB binary format. Handles decompression
        automatically if the record indicates it was compressed.

        Args:
            data: Byte data containing the serialized record
            offset: Byte offset in data where the record starts (default 0)

        Returns:
            Tuple of (bytes_read, key, value, timestamp, deleted, compressed) where:
            - bytes_read: Number of bytes consumed from data
            - key: Decoded key string
            - value: Decompressed value bytes (if was compressed)
            - timestamp: Original write timestamp
            - deleted: Whether this is a deletion marker
            - compressed: Whether the original value was compressed

        Raises:
            SerializationError: If deserialization fails or data is incomplete

        Example:
            >>> bytes_read, key, value, ts, deleted, compressed = Serializer.deserialize_record(data)
            >>> print(f"Read {bytes_read} bytes, key={key}, deleted={deleted}")

        """
        try:
            position = offset

            if position + 4 > len(data):
                raise SerializationError("Incomplete key length header")
            key_length = cls._STRUCT_KEY_LENGTH.unpack_from(data, position)[0]
            position += 4

            if position + key_length > len(data):
                raise SerializationError("Incomplete key data")
            key = data[position : position + key_length].decode("utf-8")
            position += key_length

            if position + 4 > len(data):
                raise SerializationError("Incomplete value length header")
            value_length = cls._STRUCT_VALUE_LENGTH.unpack_from(data, position)[0]
            position += 4

            if position + value_length > len(data):
                raise SerializationError("Incomplete value data")
            value = data[position : position + value_length]
            position += value_length

            if position + 8 > len(data):
                raise SerializationError("Incomplete timestamp")
            timestamp = cls._STRUCT_TIMESTAMP.unpack_from(data, position)[0]
            position += 8

            if position + 1 > len(data):
                raise SerializationError("Incomplete deleted marker")
            deleted = data[position : position + 1] == TOMBSTONE_MARKER
            position += 1

            if position + 1 > len(data):
                raise SerializationError("Incomplete compression marker")
            compressed = data[position : position + 1] == COMPRESSION_MARKER
            position += 1

            bytes_read = position - offset

            if compressed and not deleted:
                try:
                    value = zlib.decompress(value)
                except Exception as e:
                    raise SerializationError(f"Failed to decompress value: {e}") from e

            return bytes_read, key, value, timestamp, deleted, compressed

        except SerializationError:
            raise
        except Exception as e:
            raise SerializationError(f"Failed to deserialize record: {e}") from e

    @classmethod
    def write_record_to_file(
        cls,
        file_object,
        key: str,
        value: bytes,
        timestamp: int,
        deleted: bool = False,
        compress: bool = False,
    ) -> int:
        """Write a serialized record to a file.

        Serializes a record and writes it to the provided file object.
        Convenience method combining serialization and file writing.

        Args:
            file_object: Opened file object to write to
            key: The key string
            value: The value bytes
            timestamp: Write timestamp
            deleted: Whether this is a deletion marker
            compress: Whether to compress the value if beneficial

        Returns:
            Number of bytes written to the file

        Raises:
            SerializationError: If serialization or writing fails

        Example:
            >>> with open("data.sstable", "wb") as f:
            ...     bytes_written = Serializer.write_record_to_file(f, "key1", b"value1", 12345)

        """
        try:
            record = cls.serialize_record(key, value, timestamp, deleted, compress)
            file_object.write(record)
            return len(record)
        except Exception as e:
            raise SerializationError(f"Failed to write record to file: {e}") from e

    @classmethod
    def read_record_from_file(
        cls, file_object, offset: int = 0
    ) -> Tuple[int, str, bytes, int, bool, bool]:
        """Read and deserialize a record from a file.

        Reads record data from a file object and deserializes it. Handles
        decompression automatically if needed.

        Args:
            file_object: Opened file object to read from
            offset: Not used, present for API consistency (always reads from current position)

        Returns:
            Tuple of (bytes_read, key, value, timestamp, deleted, compressed) where:
            - bytes_read: Number of bytes read from file (before decompression)
            - key: Decoded key string
            - value: Decompressed value bytes (if was compressed)
            - timestamp: Original write timestamp
            - deleted: Whether this is a deletion marker
            - compressed: Whether the original value was compressed

        Raises:
            SerializationError: If reading or deserialization fails

        Example:
            >>> with open("data.sstable", "rb") as f:
            ...     bytes_read, key, value, ts, deleted, compressed = Serializer.read_record_from_file(f)
            ...     print(f"Read record: key={key}, size={len(value)} bytes")

        """
        try:
            header = file_object.read(4)
            if len(header) < 4:
                raise SerializationError("End of file reached")
            key_length = cls._STRUCT_KEY_LENGTH.unpack(header)[0]

            key_data = file_object.read(key_length)
            if len(key_data) < key_length:
                raise SerializationError("Incomplete key")
            key = key_data.decode("utf-8")

            value_length_header = file_object.read(4)
            if len(value_length_header) < 4:
                raise SerializationError("Incomplete value length")
            value_length = cls._STRUCT_VALUE_LENGTH.unpack(value_length_header)[0]

            value = file_object.read(value_length)
            if len(value) < value_length:
                raise SerializationError("Incomplete value")

            timestamp_header = file_object.read(8)
            if len(timestamp_header) < 8:
                raise SerializationError("Incomplete timestamp")
            timestamp = cls._STRUCT_TIMESTAMP.unpack(timestamp_header)[0]

            deleted_marker = file_object.read(1)
            if len(deleted_marker) < 1:
                raise SerializationError("Incomplete deleted marker")
            deleted = deleted_marker == TOMBSTONE_MARKER

            compression_marker = file_object.read(1)
            if len(compression_marker) < 1:
                raise SerializationError("Incomplete compression marker")
            compressed = compression_marker == COMPRESSION_MARKER

            if compressed and not deleted:
                try:
                    value = zlib.decompress(value)
                except Exception as e:
                    raise SerializationError(f"Failed to decompress: {e}") from e

            bytes_read = 4 + key_length + 4 + value_length + 8 + 1 + 1

            return bytes_read, key, value, timestamp, deleted, compressed

        except SerializationError:
            raise
        except Exception as e:
            raise SerializationError(f"Failed to read record from file: {e}") from e

    @classmethod
    def clear_key_cache(cls) -> None:
        """Clear the key string cache.

        Removes all cached encoded keys from memory. Useful for testing or
        when memory needs to be reclaimed. The cache will be repopulated
        as new keys are encountered.

        Example:
            >>> Serializer.clear_key_cache()
            >>> # Cache starts fresh, keys will be re-encoded on next use

        """
        cls._key_cache.clear()
        cls._cache_size = 0
