# YellowDB

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A high-performance **Log-Structured Merge-tree (LSM-tree) based key-value database** written in Python. YellowDB is designed for write-heavy workloads with excellent read performance, combining the benefits of in-memory speed with persistent on-disk storage.

```python
from yellowdb import YellowDB

# Create a database
db = YellowDB(data_directory="./my_database")

# Store data
db.set("user:1", b"Alice")
value = db.get("user:1")  # Returns: b"Alice"

# Clean up
db.close()
```

## ✨ Key Features

- **LSM-tree Architecture**: Optimized for write-heavy workloads with fast sequential writes
- **Write-Ahead Logging (WAL)**: ACID-like durability guarantees with crash recovery
- **Concurrent Operations**: Thread-safe operations with support for concurrent reads and writes
- **Automatic Compaction**: Background compaction optimizes storage and read performance
- **Caching Layer**: Built-in write-through cache for frequently accessed data
- **Bloom Filters**: Efficient key lookups without unnecessary disk I/O
- **Batch Operations**: Atomic multi-key operations for consistency
- **Range Queries**: Efficient range scans and iterators over sorted keys
- **Configuration**: Flexible configuration for tuning memory, cache, and compaction behavior

## 🚀 Quick Start

### Installation

```bash
pip install yellowdb
```

### Basic Usage

```python
from yellowdb import YellowDB

# Create and use a database
with YellowDB(data_directory="./my_database") as db:
    # Write operations
    db.set("key", b"value")

    # Read operations
    value = db.get("key")
    print(value)  # b"value"

    # Delete operations
    db.delete("key")

    # Range queries
    for key, value in db.range("start_key", "end_key"):
        print(f"{key}: {value}")

    # Full database scan
    for key, value in db.scan():
        print(f"{key}: {value}")
```

## 📚 Core Concepts

### LSM-Tree Architecture

YellowDB implements the Log-Structured Merge-tree (LSM-tree) data structure, which:

1. **Writes** are initially buffered in an in-memory structure (memtable)
2. **Write-Ahead Log (WAL)** ensures durability before acknowledgment
3. When memtables reach capacity, they're **flushed to disk as SSTables** (Sorted String Tables)
4. **Compaction** periodically merges SSTables, removing deleted entries and optimizing the tree structure

This design provides:
- Fast writes (appending to log)
- Efficient reads (cached data + tree structure)
- Automatic storage optimization (compaction)

### Components

| Component | Purpose |
|-----------|---------|
| **Memtable** | In-memory sorted buffer for pending writes |
| **SSTable** | Immutable on-disk sorted file containing key-value pairs |
| **WAL** | Write-Ahead Log for crash recovery and durability |
| **Compactor** | Background process managing SSTable merging |
| **Bloom Filter** | Probabilistic data structure for fast key lookups |
| **Cache** | Write-through cache for frequently accessed entries |

## 💻 Usage Examples

### Basic CRUD Operations

```python
from yellowdb import YellowDB

db = YellowDB(data_directory="./my_db")

# Create/Update
db.set("user:100", b'{"name": "Alice", "age": 30}')

# Read
user_data = db.get("user:100")
if user_data:
    print(user_data.decode())

# Delete
db.delete("user:100")

db.close()
```

### Batch Operations

Perform multiple operations atomically:

```python
from yellowdb import YellowDB, Batch

db = YellowDB()

# Execute multiple operations in a single batch
with Batch(db) as batch:
    batch.put("user:1", b"Alice")
    batch.put("user:2", b"Bob")
    batch.put("user:3", b"Charlie")
    batch.delete("user:4")

db.close()
```

### Range Queries

Query all entries within a key range:

```python
# Get all users between user:100 and user:200
for key, value in db.range("user:100", "user:200"):
    print(f"Key: {key}, Value: {value}")
```

### Database Iteration

Scan all entries in sorted order:

```python
# Iterate from the beginning
for key, value in db.scan():
    print(f"{key}: {value}")

# Iterate from a specific key
for key, value in db.scan(start_key="user:50"):
    print(f"{key}: {value}")
```

### Statistics and Monitoring

```python
stats = db.stats()
print(f"Get operations: {stats['stats']['get_count']}")
print(f"Set operations: {stats['stats']['set_count']}")
print(f"Cache hits: {stats['stats']['cache_hits']}")
print(f"Memtable size: {stats['memtable']['size']} bytes")
print(f"Cache entries: {stats['cache']['entries']}")
```

### Flushing and Compaction

```python
# Manually flush memtable to disk
db.flush()

# Manually trigger compaction
db.compact()

# Check if database is closed
if not db.is_closed():
    print("Database is still open")
```

## ⚙️ Configuration

The `Config` class provides singleton configuration for the database:

```python
from yellowdb import YellowDB, Config

# Get the configuration instance
config = Config()

# Set data directory
config.set_data_directory("./my_database")

# Configure memtable size (default: 64 MB)
config.memtable_size = 128 * 1024 * 1024

# Enable/disable caching (default: True)
config.enable_cache = True

# Configure cache size (default: 256 MB)
config.set_cache_size(512 * 1024 * 1024)

# Create database with custom configuration
db = YellowDB()
```

**Key Configuration Options:**

- `data_directory`: Path to store database files (default: `./yellowdb_data`)
- `memtable_size`: Maximum size of memtable before flushing (default: 64 MB)
- `enable_cache`: Enable write-through caching (default: True)
- `cache_size`: Size of the cache layer (default: 256 MB)
- `enable_concurrent_memtables`: Use multiple memtables for higher write throughput (default: False)
- `compression_level`: Compression level for SSTables (default: 6)
- `enable_compression`: Enable data compression (default: True)

## 🌍 Real-World Examples

YellowDB includes production-ready examples for common use cases:

### Session Storage

Replace Redis/Memcached for web session storage:

```python
from examples.session_store import SessionStore

store = SessionStore(ttl_seconds=3600)
session_id = store.create_session("user:100", {"ip": "192.168.1.1"})
session_data = store.get_session(session_id)
```

See [examples/session_store.py](examples/session_store.py) for Flask/FastAPI integration patterns.

### Application Caching

Cache API responses, database queries, and expensive computations:

```python
from examples.cache_layer import CacheLayer

cache = CacheLayer(default_ttl=3600)

# Cache-aside pattern
user = cache.get(
    "user:100",
    loader_fn=lambda: expensive_db_query(),
    ttl=3600
)

# Get cache statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate_percent']:.1f}%")
```

See [examples/cache_layer.py](examples/cache_layer.py) for more details.

For comprehensive examples and integration guides, see [examples/README.md](examples/README.md).

## 📖 API Reference

### YellowDB Class

```python
class YellowDB:
    """Main database class for key-value operations."""

    def __init__(self, data_directory: Optional[str] = None)
    def set(self, key: str, value: bytes) -> None
    def get(self, key: str) -> Optional[bytes]
    def delete(self, key: str) -> None
    def flush(self) -> None
    def compact(self) -> None
    def scan(self, start_key: Optional[str] = None) -> DatabaseIterator
    def range(self, start_key: str, end_key: str) -> RangeIterator
    def stats(self) -> Dict[str, Any]
    def is_closed(self) -> bool
    def close(self) -> None
    def destroy(self) -> None
    def __enter__(self) -> YellowDB
    def __exit__(self, *args) -> None
```

### Batch Class

```python
class Batch:
    """Atomic batch of database operations."""

    def __init__(self, database: YellowDB)
    def put(self, key: str, value: bytes) -> None
    def delete(self, key: str) -> None
    def commit(self) -> None
    def __enter__(self) -> Batch
    def __exit__(self, *args) -> None
```

### Iterators

```python
class DatabaseIterator:
    """Iterator for scanning all entries in sorted order."""
    def __iter__(self)
    def __next__(self) -> Tuple[str, bytes]

class RangeIterator:
    """Iterator for range queries."""
    def __iter__(self)
    def __next__(self) -> Tuple[str, bytes]
```

### Configuration

```python
class Config:
    """Singleton configuration class."""

    @classmethod
    def reset(cls) -> None

    def set_data_directory(self, path: str) -> None
    def set_cache_size(self, size: int) -> None
    def set_memtable_size(self, size: int) -> None
    def set_compression_level(self, level: int) -> None
```

### Exceptions

All database errors inherit from `YellowDBError`:

```python
from yellowdb import (
    YellowDBError,           # Base exception
    DatabaseClosedError,     # Accessing closed database
    DatabaseCorruptedError,  # Corruption detected
    InvalidKeyError,         # Invalid key
    InvalidValueError,       # Invalid value
    KeyNotFoundError,        # Key not found
    CompactionError,         # Compaction failed
    WALError,                # Write-ahead log error
    SerializationError,      # Serialization failed
    ConfigurationError,      # Configuration error
)
```

## 📊 Performance Characteristics

**Write Throughput**: ~50,000-100,000 operations/sec (depending on value size and configuration)

**Read Throughput**: ~100,000+ operations/sec (with caching enabled)

**Key-Value Size Limits**:
- Keys: Maximum 1024 bytes
- Values: Maximum 512 MB

**Typical Memory Usage**:
- Memtable: Configurable (default 64 MB)
- Cache: Configurable (default 256 MB)
- Per-entry overhead: ~50-100 bytes

**Performance Tips**:
- Enable caching for read-heavy workloads
- Use batch operations for bulk writes
- Tune memtable size based on available memory
- Configure compression for I/O-bound workloads
- Use concurrent memtables for very high write throughput

## 🛠️ Development

### Prerequisites

- Python 3.11+
- `pip` package manager

### Install Development Dependencies

```bash
pip install -e ".[dev]"
```

### Linting and Formatting

The project uses `ruff` for code quality:

```bash
# Check code style
ruff check .

# Format code
ruff format .
```

### Running Examples

```bash
# Session storage example
python examples/session_store.py

# Caching layer example
python examples/cache_layer.py
```

### Cleanup

```bash
# Remove test databases created by examples
rm -rf session_db cache_db yellowdb_data
```

## 🤝 Contributing

Contributions are welcome! To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run linting (`ruff check . && ruff format .`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Copyright (c) 2025 Arshia Ahmadzadeh

## 📖 Documentation & Resources

- **Repository**: [github.com/arshia-ahmadzadeh/yellowdb](https://github.com/arshia-ahmadzadeh/yellowdb)
- **Bug Tracker**: [GitHub Issues](https://github.com/arshia-ahmadzadeh/yellowdb/issues)
- **Examples**: [examples/README.md](examples/README.md)
- **PyPI**: [pypi.org/project/yellowdb](https://pypi.org/project/yellowdb/)

## 🎓 Learning Resources

- **LSM-Trees**: [Original LSM-Tree Paper](https://citeseer.ist.psu.edu/viewdoc/download?doi=10.1.1.44.2782&rep=rep1&type=pdf)
- **Log-Structured Storage**: [RocksDB Documentation](https://github.com/facebook/rocksdb/wiki)
- **Python Best Practices**: [PEP 8](https://www.python.org/dev/peps/pep-0008/)

---

**Built with ❤️ in Python** | MIT Licensed | v1.0.0
