"""YellowDB compaction module.

Handles background compaction of SSTables to optimize storage and read
performance by merging overlapping tables and removing deleted entries.
"""

from .compactor import Compactor

__all__ = ["Compactor"]
