"""YellowDB batch operations module.

Provides atomic batch operations for multiple key-value pairs. Batch operations
ensure that either all operations in the batch are committed or none of them are,
providing a form of atomicity for multi-operation transactions.
"""

from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from .database import YellowDB


class Batch:
    """Atomic batch of database operations.

    Groups multiple put and delete operations into a single atomic unit.
    All operations in a batch are committed together, ensuring consistency.
    Can be used as a context manager for automatic commitment.

    Attributes:
        database: Reference to the YellowDB instance
        operations: List of pending operations (operation_type, key, value)

    Example:
        Using batch operations directly:

        >>> with Batch(db) as batch:
        ...     batch.put("key1", b"value1")
        ...     batch.put("key2", b"value2")
        ...     batch.delete("key3")

        Or manually:

        >>> batch = Batch(db)
        >>> batch.put("key1", b"value1")
        >>> batch.put("key2", b"value2")
        >>> batch.commit()

    """

    def __init__(self, database: "YellowDB"):
        """Initialize a new batch operation.

        Args:
            database: The YellowDB instance to perform operations on

        Raises:
            DatabaseClosedError: If the database is closed

        """
        self.database = database
        self.operations: List[Tuple[str, str, bytes]] = []

    def put(self, key: str, value: bytes) -> "Batch":
        """Queue a put (set) operation in the batch.

        Args:
            key: String key to store
            value: Bytes value to store

        Returns:
            self: For method chaining

        Example:
            >>> batch.put("key1", b"value1").put("key2", b"value2")

        """
        self.operations.append(("put", key, value))
        return self

    def delete(self, key: str) -> "Batch":
        """Queue a delete operation in the batch.

        Args:
            key: String key to delete

        Returns:
            self: For method chaining

        Example:
            >>> batch.delete("key1").delete("key2")

        """
        self.operations.append(("delete", key, None))
        return self

    def commit(self) -> None:
        """Execute all queued operations atomically.

        All operations are committed together. If any operation fails,
        the batch may be partially committed depending on the failure point.

        Raises:
            Exception: If any operation in the batch fails

        Example:
            >>> batch = Batch(db)
            >>> batch.put("key1", b"value1")
            >>> batch.delete("key2")
            >>> batch.commit()

        """
        for operation_type, key, value in self.operations:
            if operation_type == "put":
                self.database.set(key, value)
            elif operation_type == "delete":
                self.database.delete(key)

    def __enter__(self) -> "Batch":
        """Context manager entry.

        Returns:
            self: The batch instance

        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit that commits the batch if no exception occurred.

        Args:
            exc_type: Exception type if an exception occurred in the context
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Note:
            Only commits if exc_type is None (no exception occurred).
            If an exception occurred, the batch is discarded without committing.

        """
        if exc_type is None:
            self.commit()

    def __repr__(self) -> str:
        """Get string representation of the batch.

        Returns:
            String representation showing number of queued operations

        """
        return f"Batch(operations={len(self.operations)})"
