"""YellowDB public API module.

This module exposes the main user-facing classes and interfaces for YellowDB:
- YellowDB: Main database class for all operations
- Batch: Atomic batch operations
- DatabaseIterator: Iterator for scanning all entries
- RangeIterator: Iterator for range queries
"""

from .batch import Batch
from .database import YellowDB
from .iterator import DatabaseIterator, RangeIterator

__all__ = [
    "YellowDB",
    "Batch",
    "DatabaseIterator",
    "RangeIterator",
]
