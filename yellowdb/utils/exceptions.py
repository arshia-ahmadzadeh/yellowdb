"""YellowDB exception classes.

Provides a hierarchy of custom exceptions for YellowDB operations. All exceptions
inherit from YellowDBError, allowing users to catch all YellowDB-related
exceptions with a single except clause.
"""


class YellowDBError(Exception):
    """Base exception class for all YellowDB errors.

    All YellowDB-specific exceptions inherit from this class, allowing
    users to catch any YellowDB error with `except YellowDBError:`.

    Example:
        >>> try:
        ...     db.set("key", b"value")
        ... except YellowDBError as e:
        ...     print(f"Database error: {e}")

    """

    pass


class DatabaseClosedError(YellowDBError):
    """Raised when attempting to use a closed database.

    This exception indicates that an operation was attempted on a database
    instance that has been closed via close() or destroy().

    Example:
        >>> db.close()
        >>> db.get("key")  # Raises DatabaseClosedError

    """

    pass


class DatabaseCorruptedError(YellowDBError):
    """Raised when database corruption is detected.

    This exception indicates that the database files are corrupted or in an
    inconsistent state. Recovery from WAL may be needed.

    Example:
        >>> try:
        ...     db = YellowDB(data_directory="./corrupted_db")
        ... except DatabaseCorruptedError:
        ...     print("Database is corrupted")

    """

    pass


class InvalidKeyError(YellowDBError):
    """Raised when a key fails validation.

    Keys must be non-empty strings with maximum length of 1024 bytes.

    Validation failures:
        - Key is not a string
        - Key is empty string
        - Key exceeds 1024 bytes

    Example:
        >>> db.set("", b"value")  # Raises InvalidKeyError (empty key)
        >>> db.set(123, b"value")  # Raises InvalidKeyError (not string)

    """

    pass


class InvalidValueError(YellowDBError):
    """Raised when a value fails validation.

    Values must be bytes objects with maximum size of 512MB.

    Validation failures:
        - Value is not bytes
        - Value exceeds 512MB

    Example:
        >>> db.set("key", "string")  # Raises InvalidValueError (not bytes)
        >>> db.set("key", b"x" * (512*1024*1024 + 1))  # Raises InvalidValueError (too large)

    """

    pass


class KeyNotFoundError(YellowDBError):
    """Raised when a key is not found in the database.

    Note: In normal usage, get() returns None for missing keys rather than
    raising this exception. This exception is raised in specific contexts
    where key existence is required.

    Example:
        >>> try:
        ...     db.get("nonexistent")
        ... except KeyNotFoundError:
        ...     pass  # Usually get() returns None instead

    """

    pass


class CompactionError(YellowDBError):
    """Raised when a compaction operation fails.

    This exception indicates an error during background compaction,
    such as I/O errors when merging SSTables.

    Example:
        >>> try:
        ...     db.compact()
        ... except CompactionError as e:
        ...     print(f"Compaction failed: {e}")

    """

    pass


class WALError(YellowDBError):
    """Raised when Write-Ahead Log operations fail.

    This exception indicates failures in WAL writing, reading, or rotation,
    which are critical for database durability.

    Example:
        >>> try:
        ...     db.set("key", b"value")
        ... except WALError as e:
        ...     print(f"WAL write failed: {e}")

    """

    pass


class SerializationError(YellowDBError):
    """Raised when serialization/deserialization of data fails.

    This exception indicates errors when converting between Python objects
    and their serialized representation for storage.

    Example:
        >>> try:
        ...     db.set("key", b"value")
        ... except SerializationError as e:
        ...     print(f"Serialization failed: {e}")

    """

    pass


class ConfigurationError(YellowDBError):
    """Raised when database configuration is invalid.

    This exception indicates invalid configuration parameters such as
    negative sizes or invalid option values.

    Example:
        >>> config = Config()
        >>> config.set_memtable_size(-1)  # Raises ConfigurationError

    """

    pass


class IOError(YellowDBError):
    """Raised when file I/O operations fail.

    This exception wraps I/O errors when reading or writing database files,
    such as permission errors or disk full conditions.

    Example:
        >>> try:
        ...     db = YellowDB(data_directory="/read-only-path")
        ... except IOError as e:
        ...     print(f"I/O error: {e}")

    """

    pass
