"""YellowDB cache module.

Provides caching mechanisms to speed up read operations by maintaining
frequently accessed key-value pairs in memory.
"""

from .write_through import WriteThroughCache

__all__ = ["WriteThroughCache"]
