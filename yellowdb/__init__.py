"""YellowDB: A high-performance Log-Structured Merge-tree (LSM-tree) based key-value database.

YellowDB is an embedded, pure Python database implementation designed for write-heavy
workloads with excellent read performance. It provides ACID-like semantics with
write-ahead logging, concurrent operations, automatic compaction, and optional caching.

Main Classes:
    YellowDB: Main database class for all operations
    Batch: Atomic batch operations for multiple key-value pairs
    DatabaseIterator: Iterator for scanning all entries in sorted order
    RangeIterator: Iterator for range-based queries

Configuration:
    Config: Singleton configuration class for database parameters

Exceptions:
    YellowDBError: Base exception class
    DatabaseClosedError: Raised when accessing a closed database
    DatabaseCorruptedError: Raised when database corruption is detected
    InvalidKeyError: Raised when key validation fails
    InvalidValueError: Raised when value validation fails
    KeyNotFoundError: Raised when a key is not found
    CompactionError: Raised when compaction fails
    WALError: Raised when write-ahead log operations fail
    SerializationError: Raised when serialization fails
    ConfigurationError: Raised when configuration is invalid

Example:
    Basic usage:

    >>> from yellowdb import YellowDB
    >>> db = YellowDB(data_directory="./my_database")
    >>> db.set("user:1", b"Alice")
    >>> value = db.get("user:1")
    >>> db.close()

    Using context manager:

    >>> with YellowDB() as db:
    ...     db.set("key", b"value")
    ...     print(db.get("key"))

"""

from .api import Batch, DatabaseIterator, RangeIterator, YellowDB
from .utils.config import Config
from .utils.exceptions import (
    CompactionError,
    ConfigurationError,
    DatabaseClosedError,
    DatabaseCorruptedError,
    InvalidKeyError,
    InvalidValueError,
    IOError,
    KeyNotFoundError,
    SerializationError,
    WALError,
    YellowDBError,
)

__version__ = "1.0.0"
__author__ = "Arshia Ahmadzadeh"

__all__ = [
    "YellowDB",
    "Batch",
    "DatabaseIterator",
    "RangeIterator",
    "Config",
    "YellowDBError",
    "DatabaseClosedError",
    "DatabaseCorruptedError",
    "InvalidKeyError",
    "InvalidValueError",
    "KeyNotFoundError",
    "CompactionError",
    "WALError",
    "SerializationError",
    "ConfigurationError",
    "IOError",
]
