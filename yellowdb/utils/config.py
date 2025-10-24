"""YellowDB configuration module.

Provides a singleton configuration class that centralizes all tunable parameters
for YellowDB operation. Configuration affects behavior of memtables, caching,
compression, compaction, and write-ahead logging.

All configuration parameters have sensible defaults but can be customized for
different workload requirements.
"""

from pathlib import Path
from typing import Optional


class Config:
    """Singleton configuration for YellowDB parameters.

    Centralizes all tunable configuration parameters in a single location.
    Uses the singleton pattern to ensure consistent configuration across
    the entire application. All parameters have defaults but can be customized
    before creating the first YellowDB instance.

    Class Attributes:
        DEFAULT_DATA_DIRECTORY: Path for database files (./yellowdb_data)
        DEFAULT_ENABLE_READ_ONLY_MODE: Read-only mode flag (False)
        DEFAULT_LOG_LEVEL: Logging level (INFO)
        DEFAULT_MEMTABLE_SIZE: Memtable size in bytes (64MB)
        DEFAULT_CONCURRENT_MEMTABLE_COUNT: Number of concurrent memtables (4)
        DEFAULT_ENABLE_CONCURRENT_MEMTABLES: Enable concurrent memtables (True)
        DEFAULT_WRITE_BUFFER_SIZE: Write buffer size in bytes (256MB)
        DEFAULT_SSTABLE_SIZE: SSTable size in bytes (128MB)
        DEFAULT_BLOCK_SIZE: Data block size in bytes (4096)
        DEFAULT_SPARSE_INDEX_INTERVAL: Sparse index interval (32)
        DEFAULT_CACHE_SIZE: Cache size in bytes (512MB)
        DEFAULT_ENABLE_CACHE: Enable caching (True)
        DEFAULT_BLOOM_FILTER_SIZE: Bloom filter size in items (100000)
        DEFAULT_BLOOM_FILTER_HASH_FUNCTIONS: Bloom filter hash functions (3)
        DEFAULT_ENABLE_BLOOM_FILTER: Enable bloom filters (True)
        DEFAULT_COMPRESSION_THRESHOLD: Minimum value size to compress (10KB)
        DEFAULT_COMPRESSION_LEVEL: Compression level 1-9 (6)
        DEFAULT_ENABLE_COMPRESSION: Enable compression (True)
        DEFAULT_COMPACTION_STRATEGY: Compaction strategy (tiered)
        DEFAULT_COMPACTION_THRESHOLD: Compaction trigger threshold (4)
        DEFAULT_LAZY_COMPACTION: Lazy compaction flag (True)
        DEFAULT_MAX_CONCURRENT_COMPACTIONS: Max concurrent compactions (2)
        DEFAULT_WAL_BATCH_SIZE: WAL batch size (100)
        DEFAULT_WAL_SYNC_INTERVAL: WAL sync interval in bytes (1MB)
        DEFAULT_SYNC_WAL: Sync WAL on every write (False)

    Instance Attributes:
        data_directory: Path to database files
        enable_read_only_mode: Whether to run in read-only mode
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        memtable_size: Maximum memtable size in bytes
        concurrent_memtable_count: Number of concurrent memtables
        enable_concurrent_memtables: Whether to use concurrent memtables
        write_buffer_size: Total write buffer size in bytes
        sstable_size: Target SSTable size in bytes
        block_size: Data block size for SSTables in bytes
        sparse_index_interval: Interval for sparse indexing
        cache_size: Write-through cache size in bytes
        enable_cache: Whether to enable caching
        bloom_filter_size: Number of items in bloom filters
        bloom_filter_hash_functions: Number of hash functions in bloom filters
        enable_bloom_filter: Whether to enable bloom filters
        compression_threshold: Minimum value size to compress in bytes
        compression_level: Compression level from 1-9
        enable_compression: Whether to enable compression
        compaction_strategy: Strategy for compaction (tiered, leveled, etc)
        compaction_threshold: Number of SSTables before compaction triggers
        lazy_compaction: Whether compaction runs in background
        max_concurrent_compactions: Maximum concurrent compaction operations
        wal_batch_size: Number of entries to batch in WAL
        wal_sync_interval: Bytes written before syncing WAL
        sync_wal: Whether to sync WAL on every write

    Example:
        Configure before creating database:

        >>> config = Config()
        >>> config.set_memtable_size(128 * 1024 * 1024)  # 128MB
        >>> config.set_cache_size(256 * 1024 * 1024)  # 256MB
        >>> config.set_log_level("DEBUG")
        >>> db = YellowDB()  # Uses configured settings

    """

    DEFAULT_DATA_DIRECTORY = "./yellowdb_data"
    DEFAULT_ENABLE_READ_ONLY_MODE = False
    DEFAULT_LOG_LEVEL = "INFO"
    DEFAULT_MEMTABLE_SIZE = 64 * 1024 * 1024
    DEFAULT_CONCURRENT_MEMTABLE_COUNT = 4
    DEFAULT_ENABLE_CONCURRENT_MEMTABLES = True
    DEFAULT_WRITE_BUFFER_SIZE = 256 * 1024 * 1024
    DEFAULT_SSTABLE_SIZE = 128 * 1024 * 1024
    DEFAULT_BLOCK_SIZE = 4096
    DEFAULT_SPARSE_INDEX_INTERVAL = 32
    DEFAULT_CACHE_SIZE = 512 * 1024 * 1024
    DEFAULT_ENABLE_CACHE = True
    DEFAULT_BLOOM_FILTER_SIZE = 100000
    DEFAULT_BLOOM_FILTER_HASH_FUNCTIONS = 3
    DEFAULT_ENABLE_BLOOM_FILTER = True
    DEFAULT_COMPRESSION_THRESHOLD = 10 * 1024
    DEFAULT_COMPRESSION_LEVEL = 6
    DEFAULT_ENABLE_COMPRESSION = True
    DEFAULT_COMPACTION_STRATEGY = "tiered"
    DEFAULT_COMPACTION_THRESHOLD = 4
    DEFAULT_LAZY_COMPACTION = True
    DEFAULT_MAX_CONCURRENT_COMPACTIONS = 2
    DEFAULT_WAL_BATCH_SIZE = 100
    DEFAULT_WAL_SYNC_INTERVAL = 1024 * 1024
    DEFAULT_SYNC_WAL = False

    _instance: Optional["Config"] = None

    def __new__(cls) -> "Config":
        """Create or return the singleton Config instance.

        Returns:
            The singleton Config instance. Multiple calls return the same object.

        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize the configuration with default values.

        Only initializes once due to singleton pattern. Subsequent calls
        are ignored to preserve existing configuration.
        """
        if self._initialized:
            return

        self.data_directory: Path = Path(self.DEFAULT_DATA_DIRECTORY)
        self.enable_read_only_mode: bool = self.DEFAULT_ENABLE_READ_ONLY_MODE
        self.log_level: str = self.DEFAULT_LOG_LEVEL
        self.memtable_size: int = self.DEFAULT_MEMTABLE_SIZE
        self.concurrent_memtable_count: int = self.DEFAULT_CONCURRENT_MEMTABLE_COUNT
        self.enable_concurrent_memtables: bool = self.DEFAULT_ENABLE_CONCURRENT_MEMTABLES
        self.write_buffer_size: int = self.DEFAULT_WRITE_BUFFER_SIZE
        self.sstable_size: int = self.DEFAULT_SSTABLE_SIZE
        self.block_size: int = self.DEFAULT_BLOCK_SIZE
        self.sparse_index_interval: int = self.DEFAULT_SPARSE_INDEX_INTERVAL
        self.cache_size: int = self.DEFAULT_CACHE_SIZE
        self.enable_cache: bool = self.DEFAULT_ENABLE_CACHE
        self.bloom_filter_size: int = self.DEFAULT_BLOOM_FILTER_SIZE
        self.bloom_filter_hash_functions: int = self.DEFAULT_BLOOM_FILTER_HASH_FUNCTIONS
        self.enable_bloom_filter: bool = self.DEFAULT_ENABLE_BLOOM_FILTER
        self.compression_threshold: int = self.DEFAULT_COMPRESSION_THRESHOLD
        self.compression_level: int = self.DEFAULT_COMPRESSION_LEVEL
        self.enable_compression: bool = self.DEFAULT_ENABLE_COMPRESSION
        self.compaction_strategy: str = self.DEFAULT_COMPACTION_STRATEGY
        self.compaction_threshold: int = self.DEFAULT_COMPACTION_THRESHOLD
        self.lazy_compaction: bool = self.DEFAULT_LAZY_COMPACTION
        self.max_concurrent_compactions: int = self.DEFAULT_MAX_CONCURRENT_COMPACTIONS
        self.wal_batch_size: int = self.DEFAULT_WAL_BATCH_SIZE
        self.wal_sync_interval: int = self.DEFAULT_WAL_SYNC_INTERVAL
        self.sync_wal: bool = self.DEFAULT_SYNC_WAL

        self._initialized = True

    def set_data_directory(self, path: str) -> None:
        """Set the database data directory path.

        Args:
            path: Path to directory where database files are stored.
                  Directory will be created if it doesn't exist.

        Example:
            >>> config.set_data_directory("/var/lib/yellowdb")

        """
        self.data_directory = Path(path)

    def set_log_level(self, level: str) -> None:
        """Set the logging level.

        Args:
            level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL

        Raises:
            ValueError: If level is not a valid logging level

        Example:
            >>> config.set_log_level("DEBUG")

        """
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level not in valid_levels:
            raise ValueError(f"Invalid log level. Must be one of {valid_levels}")
        self.log_level = level

    def set_memtable_size(self, size: int) -> None:
        """Set the memtable size in bytes.

        Larger memtables reduce compaction overhead but use more memory.
        The memtable is flushed to disk when it reaches this size.

        Args:
            size: Size in bytes (must be positive)

        Raises:
            ValueError: If size is not positive

        Example:
            >>> config.set_memtable_size(128 * 1024 * 1024)  # 128MB

        """
        if size <= 0:
            raise ValueError("Memtable size must be positive")
        self.memtable_size = size

    def set_sstable_size(self, size: int) -> None:
        """Set the target SSTable size in bytes.

        SSTables are the on-disk sorted files. Larger tables reduce
        the number of files but increase compaction overhead.

        Args:
            size: Size in bytes (must be positive)

        Raises:
            ValueError: If size is not positive

        Example:
            >>> config.set_sstable_size(256 * 1024 * 1024)  # 256MB

        """
        if size <= 0:
            raise ValueError("SSTable size must be positive")
        self.sstable_size = size

    def set_cache_size(self, size: int) -> None:
        """Set the write-through cache size in bytes.

        Cache improves read performance for frequently accessed data.
        Set to 0 to disable caching.

        Args:
            size: Size in bytes (cannot be negative)

        Raises:
            ValueError: If size is negative

        Example:
            >>> config.set_cache_size(256 * 1024 * 1024)  # 256MB

        """
        if size < 0:
            raise ValueError("Cache size cannot be negative")
        self.cache_size = size

    def set_compression_threshold(self, threshold: int) -> None:
        """Set the minimum value size to compress in bytes.

        Values smaller than this threshold are not compressed.
        Set to 0 to compress all values.

        Args:
            threshold: Size in bytes (cannot be negative)

        Raises:
            ValueError: If threshold is negative

        Example:
            >>> config.set_compression_threshold(4 * 1024)  # 4KB

        """
        if threshold < 0:
            raise ValueError("Compression threshold cannot be negative")
        self.compression_threshold = threshold

    def enable_sync_wal(self, enabled: bool) -> None:
        """Enable or disable WAL syncing on every write.

        When enabled, every write is immediately synced to disk for
        maximum durability. When disabled, syncing happens periodically
        for better performance.

        Args:
            enabled: True to sync on every write, False for periodic sync

        Example:
            >>> config.enable_sync_wal(True)  # Maximum durability

        """
        self.sync_wal = enabled

    def to_dict(self) -> dict:
        """Get all configuration parameters as a dictionary.

        Useful for logging, serialization, or debugging.

        Returns:
            Dictionary with all configuration key-value pairs

        Example:
            >>> config = Config()
            >>> params = config.to_dict()
            >>> print(params)

        """
        return {
            "data_directory": str(self.data_directory),
            "log_level": self.log_level,
            "memtable_size": self.memtable_size,
            "enable_concurrent_memtables": self.enable_concurrent_memtables,
            "write_buffer_size": self.write_buffer_size,
            "sstable_size": self.sstable_size,
            "block_size": self.block_size,
            "sparse_index_interval": self.sparse_index_interval,
            "cache_size": self.cache_size,
            "enable_cache": self.enable_cache,
            "bloom_filter_size": self.bloom_filter_size,
            "enable_bloom_filter": self.enable_bloom_filter,
            "compression_threshold": self.compression_threshold,
            "compression_level": self.compression_level,
            "enable_compression": self.enable_compression,
            "compaction_strategy": self.compaction_strategy,
            "compaction_threshold": self.compaction_threshold,
            "lazy_compaction": self.lazy_compaction,
            "wal_batch_size": self.wal_batch_size,
            "wal_sync_interval": self.wal_sync_interval,
            "sync_wal": self.sync_wal,
        }

    @classmethod
    def reset(cls) -> None:
        """Reset the configuration singleton to None.

        Used primarily for testing to clear the singleton instance
        and allow creating a fresh configuration.

        Example:
            >>> Config.reset()  # Clear singleton
            >>> config = Config()  # Create new instance with defaults

        """
        cls._instance = None
