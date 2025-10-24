"""Write-Ahead Log (WAL) module for YellowDB.

This module provides a Write-Ahead Log implementation for durability and crash recovery.
The WAL ensures that all write operations are logged to disk before being applied to the
main data structure, enabling recovery after crashes or unexpected shutdowns.

The implementation supports batching for improved write performance, automatic file rotation,
and configurable synchronization policies. All operations are thread-safe using locks.

Classes:
    WALBatch: Accumulates WAL entries for batch writing.
    WAL: Main Write-Ahead Log manager with recovery and rotation capabilities.
"""

import os
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from ..core.serializer import Serializer
from ..utils.config import Config
from ..utils.exceptions import WALError


class WALBatch:
    """Batch accumulator for WAL entries to optimize write performance.

    This class accumulates multiple WAL entries in memory before flushing them to disk
    as a single write operation, reducing the number of I/O operations and improving
    throughput.

    Thread-safety: This class is not thread-safe on its own. The WAL class that uses it
    provides the necessary synchronization.

    Attributes:
        max_size: Maximum number of entries before triggering a flush.
        entries: List of serialized record bytes pending write.
        entry_count: Current number of entries in the batch.

    """

    def __init__(self, max_size: int = 100):
        """Initialize a new WAL batch.

        Args:
            max_size: Maximum number of entries the batch can hold before requiring
                a flush. Defaults to 100.

        """
        self.max_size = max_size
        self.entries: List[bytes] = []
        self.entry_count = 0

    def add_entry(self, record: bytes) -> bool:
        """Add a serialized record to the batch.

        Args:
            record: Serialized record bytes to add to the batch.

        Returns:
            True if the batch is full after adding this entry, False otherwise.

        """
        self.entries.append(record)
        self.entry_count += 1
        return self.entry_count >= self.max_size

    def get_bytes(self) -> bytes:
        """Concatenate all batch entries into a single byte string.

        Returns:
            All entries concatenated as a single bytes object ready for writing.

        """
        return b"".join(self.entries)

    def clear(self) -> None:
        """Clear all entries from the batch, resetting it to empty state."""
        self.entries.clear()
        self.entry_count = 0

    def __len__(self) -> int:
        """Return the number of entries currently in the batch.

        Returns:
            Current entry count.

        """
        return self.entry_count


class WAL:
    """Write-Ahead Log manager for durable, crash-recoverable storage.

    The WAL provides durability guarantees by logging all write operations to disk before
    they are applied to the main data structure. This enables recovery of committed data
    after crashes or unexpected shutdowns.

    Features:
        - Batched writes for improved performance
        - Automatic file rotation
        - Configurable synchronization (fsync) policies
        - Thread-safe operations using reentrant locks
        - Recovery from multiple WAL files in sequence order

    Thread-safety: All public methods are thread-safe and can be called concurrently.

    Attributes:
        WAL_EXTENSION: File extension for WAL files (".wal").
        data_directory: Directory where WAL files are stored.
        config: Configuration object with WAL settings.

    """

    WAL_EXTENSION = ".wal"

    def __init__(self, data_directory: Path):
        """Initialize the Write-Ahead Log manager.

        Args:
            data_directory: Path to the directory where WAL files will be stored.
                The directory will be created if it doesn't exist.

        Raises:
            WALError: If the data directory cannot be created or accessed.

        """
        self.config = Config()
        self.data_directory = Path(data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._current_wal_file: Optional[Path] = None
        self._current_wal_handle = None
        self._entry_count = 0
        self._current_wal_size = 0
        self._batch_size_counter = 0

        self._batch_lock = threading.Lock()
        self._batch = WALBatch(self.config.wal_batch_size)

    def _flush_batch(self) -> None:
        """Flush the current batch buffer to disk.

        This internal method writes all accumulated entries in the batch to the WAL file.
        If sync_wal is enabled in the configuration, it also performs fsync to ensure
        data is persisted to disk.

        Raises:
            WALError: If writing or fsyncing the batch fails.

        Note:
            This method is thread-safe and uses a separate batch lock to prevent
            concurrent batch modifications.

        """
        with self._batch_lock:
            if self._batch.entry_count == 0:
                return

            try:
                batch_bytes = self._batch.get_bytes()
                self._current_wal_handle.write(batch_bytes)
                self._current_wal_size += len(batch_bytes)

                if self.config.sync_wal:
                    self._current_wal_handle.flush()
                    os.fsync(self._current_wal_handle.fileno())

                self._batch.clear()
                self._batch_size_counter = 0

            except Exception as e:
                raise WALError(f"Failed to flush WAL batch: {e}") from e

    def _get_latest_wal_sequence(self) -> int:
        """Get the highest sequence number among existing WAL files.

        Scans the data directory for WAL files with the naming pattern "wal_NNNNNN.wal"
        and returns the maximum sequence number found.

        Returns:
            The highest sequence number found, or 0 if no WAL files exist.

        Note:
            Files that don't match the expected naming pattern are silently ignored.

        """
        wal_files = list(self.data_directory.glob(f"wal_*{self.WAL_EXTENSION}"))
        if not wal_files:
            return 0

        maximum_sequence = 0
        for wal_file in wal_files:
            try:
                sequence_str = wal_file.name.replace("wal_", "").replace(self.WAL_EXTENSION, "")
                sequence = int(sequence_str)
                maximum_sequence = max(maximum_sequence, sequence)
            except ValueError:
                pass

        return maximum_sequence

    def _open_new_wal_file(self) -> None:
        """Open a new WAL file with the next sequence number.

        Closes the current WAL file (if any) after flushing pending batches, then opens
        a new WAL file with an incremented sequence number. The file is opened in append
        binary mode.

        Raises:
            WALError: If closing the current file or opening the new file fails.

        Note:
            This method resets the entry count and current WAL size counters.

        """
        try:
            if self._current_wal_handle:
                self._flush_batch()
                self._current_wal_handle.close()

            sequence = self._get_latest_wal_sequence() + 1
            self._current_wal_file = self.data_directory / self._get_wal_filename(sequence)

            self._current_wal_handle = open(self._current_wal_file, "ab")  # noqa: SIM115
            self._entry_count = 0
            self._current_wal_size = 0

        except Exception as e:
            raise WALError(f"Failed to open WAL file: {e}") from e

    def _get_wal_filename(self, sequence: int) -> str:
        """Generate a WAL filename from a sequence number.

        Args:
            sequence: The sequence number for the WAL file.

        Returns:
            Filename in the format "wal_NNNNNN.wal" where NNNNNN is the zero-padded
            sequence number.

        Example:
            >>> wal._get_wal_filename(42)
            'wal_000042.wal'

        """
        return f"wal_{sequence:06d}{self.WAL_EXTENSION}"

    def write(self, key: str, value: bytes, timestamp: int, deleted: bool = False) -> None:
        """Write a record to the Write-Ahead Log.

        The record is first added to a batch buffer. When the batch is full or exceeds
        the configured sync interval, it is flushed to disk. This method is thread-safe.

        Args:
            key: The key being written or deleted.
            value: The value associated with the key (can be empty for deletions).
            timestamp: Timestamp of the operation in nanoseconds.
            deleted: Whether this is a deletion operation. Defaults to False.

        Raises:
            WALError: If writing to the WAL fails due to I/O errors.

        Example:
            >>> wal = WAL(Path("/data/wal"))
            >>> wal.write("user:123", b"John Doe", 1234567890, deleted=False)

        """
        with self._lock:
            try:
                if self._current_wal_handle is None:
                    self._open_new_wal_file()

                record = Serializer.serialize_record(key, value, timestamp, deleted, compress=False)

                batch_full = self._batch.add_entry(record)
                self._batch_size_counter += len(record)

                if batch_full or self._batch_size_counter >= self.config.wal_sync_interval:
                    self._flush_batch()

                self._entry_count += 1

            except Exception as e:
                raise WALError(f"Failed to write to WAL: {e}") from e

    def rotate(self) -> Optional[Path]:
        """Rotate to a new WAL file, closing the current one.

        This method flushes any pending batched writes, syncs the current WAL file to disk,
        and opens a new WAL file with the next sequence number. This is typically called
        after a memtable flush to SSTable.

        Returns:
            Path to the old WAL file that was closed, or None if no WAL file was open.

        Raises:
            WALError: If rotation fails due to I/O errors.

        Example:
            >>> wal = WAL(Path("/data/wal"))
            >>> old_wal = wal.rotate()
            >>> if old_wal:
            ...     print(f"Rotated from {old_wal}")

        """
        with self._lock:
            try:
                old_wal = self._current_wal_file
                self._flush_batch()

                if old_wal and self._current_wal_handle:
                    self._current_wal_handle.flush()
                    os.fsync(self._current_wal_handle.fileno())

                self._open_new_wal_file()
                return old_wal

            except Exception as e:
                raise WALError(f"Failed to rotate WAL: {e}") from e

    def recover(self) -> List[Tuple[str, bytes, int, bool]]:
        """Recover all entries from existing WAL files.

        Reads all WAL files in sequence order and extracts all logged operations.
        This is typically called during database startup to replay uncommitted operations
        and restore the database to its last consistent state.

        Returns:
            List of tuples, each containing (key, value, timestamp, deleted) for each
            logged operation in chronological order.

        Raises:
            WALError: If recovery fails due to I/O errors or corrupted WAL files.

        Example:
            >>> wal = WAL(Path("/data/wal"))
            >>> entries = wal.recover()
            >>> for key, value, timestamp, deleted in entries:
            ...     # Replay operation to memtable
            ...     print(f"Recovered: {key}")

        """
        with self._lock:
            try:
                entries = []
                wal_files = sorted(self.data_directory.glob(f"wal_*{self.WAL_EXTENSION}"))

                for wal_file in wal_files:
                    with open(wal_file, "rb") as f:
                        while True:
                            try:
                                _, key, value, timestamp, deleted, _ = (
                                    Serializer.read_record_from_file(f)
                                )
                                entries.append((key, value, timestamp, deleted))
                            except Exception:
                                break

                return entries

            except Exception as e:
                raise WALError(f"Failed to recover from WAL: {e}") from e

    def delete_old_wal_files(self, keep_count: int = 1) -> None:
        """Delete old WAL files, keeping only the most recent ones.

        This method is used for cleanup after successful WAL recovery and SSTable flushing.
        It removes old WAL files that are no longer needed, keeping only the specified number
        of most recent files.

        Args:
            keep_count: Number of most recent WAL files to retain. Defaults to 1.

        Raises:
            WALError: If deletion fails due to permission or I/O errors.

        Example:
            >>> wal = WAL(Path("/data/wal"))
            >>> # After successful flush to SSTable
            >>> wal.delete_old_wal_files(keep_count=2)

        """
        with self._lock:
            try:
                wal_files = sorted(self.data_directory.glob(f"wal_*{self.WAL_EXTENSION}"))
                files_to_delete = wal_files[:-keep_count]

                for wal_file in files_to_delete:
                    try:
                        wal_file.unlink()
                    except Exception:
                        pass

            except Exception as e:
                raise WALError(f"Error deleting old WAL files: {e}") from e

    def close(self) -> None:
        """Close the WAL, flushing all pending writes and syncing to disk.

        This method should be called when shutting down the database to ensure all
        buffered writes are persisted. After calling close, no further writes should
        be attempted.

        Raises:
            WALError: If flushing or closing fails due to I/O errors.

        Example:
            >>> wal = WAL(Path("/data/wal"))
            >>> # ... perform writes ...
            >>> wal.close()  # Ensure all data is persisted before shutdown

        """
        with self._lock:
            try:
                self._flush_batch()

                if self._current_wal_handle:
                    self._current_wal_handle.flush()
                    os.fsync(self._current_wal_handle.fileno())
                    self._current_wal_handle.close()
                    self._current_wal_handle = None

            except Exception as e:
                raise WALError(f"Error closing WAL: {e}") from e

    def get_entry_count(self) -> int:
        """Get the number of entries written to the current WAL file.

        Returns:
            Count of entries in the current WAL file since last rotation.

        """
        return self._entry_count

    def get_size(self) -> int:
        """Get the size of the current WAL file in bytes.

        Returns:
            Size of the current WAL file in bytes, excluding any pending batched writes.

        """
        return self._current_wal_size

    def __repr__(self) -> str:
        return f"WAL(file={self._current_wal_file}, entries={self._entry_count}, size={self._current_wal_size})"
