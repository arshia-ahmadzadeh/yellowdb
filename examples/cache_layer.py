#!/usr/bin/env python3
"""Real-World Example: Application-Level Caching Layer.

This example demonstrates using YellowDB as a cache-aside pattern implementation
for APIs, databases, and external service responses.

Features demonstrated:
- Cache-aside (lazy-loading) pattern
- TTL-based expiration
- Cache warming
- Statistics tracking (hit rate, miss rate)
- Batch operations for cache seeding.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from yellowdb import Batch, YellowDB


class CacheLayer:
    """Application-level caching using YellowDB.

    Implements cache-aside pattern with TTL support.
    """

    def __init__(self, db_path: str = "./cache_db", default_ttl: int = 3600):
        """Initialize cache layer.

        Args:
            db_path: Path to YellowDB directory
            default_ttl: Default time-to-live in seconds

        """
        self.db = YellowDB(data_directory=db_path)
        self.default_ttl = default_ttl
        self.cache_prefix = "cache:"
        self.metadata_prefix = "meta:"

        # Statistics
        self.stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "evictions": 0,
        }

    def get(self, key: str, loader_fn=None, ttl: Optional[int] = None) -> Optional[Any]:
        """Get value from cache.

        If not found and loader_fn provided, load from source and cache it.

        Args:
            key: Cache key
            loader_fn: Optional function to load value if not cached
            ttl: Time-to-live in seconds (uses default if None)

        Returns:
            Cached value or None

        """
        cache_key = f"{self.cache_prefix}{key}"
        meta_key = f"{self.metadata_prefix}{key}"

        cached_bytes = self.db.get(cache_key)
        if cached_bytes:
            meta_bytes = self.db.get(meta_key)
            if meta_bytes:
                metadata = json.loads(meta_bytes.decode())
                expires_at = datetime.fromisoformat(metadata["expires_at"])
                if datetime.now() < expires_at:
                    self.stats["hits"] += 1
                    return json.loads(cached_bytes.decode())
            self.db.delete(cache_key)
            self.db.delete(meta_key)

        self.stats["misses"] += 1

        if loader_fn:
            value = loader_fn()
            self.set(key, value, ttl=ttl)
            return value

        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds

        """
        ttl = ttl or self.default_ttl
        cache_key = f"{self.cache_prefix}{key}"
        meta_key = f"{self.metadata_prefix}{key}"

        value_bytes = json.dumps(value).encode()
        metadata = {
            "key": key,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(seconds=ttl)).isoformat(),
            "ttl": ttl,
            "size_bytes": len(value_bytes),
        }
        meta_bytes = json.dumps(metadata).encode()

        with Batch(self.db) as batch:
            batch.put(cache_key, value_bytes)
            batch.put(meta_key, meta_bytes)

        self.stats["writes"] += 1

    def delete(self, key: str) -> None:
        """Remove a key from cache.

        Args:
            key: Cache key

        """
        cache_key = f"{self.cache_prefix}{key}"
        meta_key = f"{self.metadata_prefix}{key}"

        with Batch(self.db) as batch:
            batch.delete(cache_key)
            batch.delete(meta_key)

        self.stats["evictions"] += 1

    def clear_expired(self) -> int:
        """Remove all expired entries from cache.

        Returns:
            Number of entries cleaned up

        """
        expired_keys = []
        current_time = datetime.now()

        for key, value in self.db.scan(start_key=self.metadata_prefix):
            if not key.startswith(self.metadata_prefix):
                break
            metadata = json.loads(value.decode())
            expires_at = datetime.fromisoformat(metadata["expires_at"])
            if current_time > expires_at:
                original_key = metadata["key"]
                expired_keys.append(original_key)

        if expired_keys:
            with Batch(self.db) as batch:
                for original_key in expired_keys:
                    batch.delete(f"{self.cache_prefix}{original_key}")
                    batch.delete(f"{self.metadata_prefix}{original_key}")
            self.stats["evictions"] += len(expired_keys)

        return len(expired_keys)

    def warm_cache(self, data_dict: Dict[str, Any], ttl: Optional[int] = None) -> int:
        """Populate cache with multiple entries at once."""
        ttl = ttl or self.default_ttl
        current_time = datetime.now()

        with Batch(self.db) as batch:
            for key, value in data_dict.items():
                cache_key = f"{self.cache_prefix}{key}"
                meta_key = f"{self.metadata_prefix}{key}"
                value_bytes = json.dumps(value).encode()
                metadata = {
                    "key": key,
                    "created_at": current_time.isoformat(),
                    "expires_at": (current_time + timedelta(seconds=ttl)).isoformat(),
                    "ttl": ttl,
                    "size_bytes": len(value_bytes),
                }
                batch.put(cache_key, value_bytes)
                batch.put(meta_key, json.dumps(metadata).encode())

        self.stats["writes"] += len(data_dict)
        return len(data_dict)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total_requests * 100 if total_requests > 0 else 0

        cached_entries = 0
        total_size = 0
        for key, value in self.db.scan(start_key=self.metadata_prefix):
            if not key.startswith(self.metadata_prefix):
                break
            metadata = json.loads(value.decode())
            cached_entries += 1
            total_size += metadata.get("size_bytes", 0)

        db_stats = self.db.stats()

        return {
            "cache_hits": self.stats["hits"],
            "cache_misses": self.stats["misses"],
            "hit_rate_percent": hit_rate,
            "total_writes": self.stats["writes"],
            "total_evictions": self.stats["evictions"],
            "current_entries": cached_entries,
            "total_cached_size": total_size,
            "memtable_size": db_stats["memtable"]["size"],
        }

    def close(self) -> None:
        """Close the cache."""
        self.db.close()


def simulate_expensive_operation(user_id: str) -> Dict[str, Any]:
    """Simulate an expensive operation (DB query, API call, etc.)."""
    return {
        "user_id": user_id,
        "name": f"User_{user_id}",
        "email": f"user{user_id}@example.com",
        "subscription": "premium",
        "last_login": datetime.now().isoformat(),
    }


def demo_cache_layer():
    """Demonstrate cache layer functionality."""
    print("\n" + "=" * 80)
    print("APPLICATION CACHING LAYER EXAMPLE")
    print("=" * 80)

    cache = CacheLayer(db_path="./cache_db", default_ttl=5)

    print("\n1. Cache-aside pattern (lazy loading):")
    user_data = cache.get("user:100", loader_fn=lambda: simulate_expensive_operation("100"))
    print(f"   ✓ Loaded from source: {user_data['name']}")

    print("\n2. Second request (hits cache):")
    user_data = cache.get("user:100")
    print(f"   ✓ Got from cache: {user_data['name']}")

    print("\n3. Direct cache set:")
    cache.set(
        "config:app",
        {
            "max_connections": 100,
            "timeout": 30,
            "version": "2.0",
        },
    )
    config = cache.get("config:app")
    print(f"   ✓ Config: version={config['version']}")

    print("\n4. Cache warming (batch preload):")
    user_list = {f"user:{i}": simulate_expensive_operation(str(i)) for i in range(201, 206)}
    count = cache.warm_cache(user_list, ttl=60)
    print(f"   ✓ Preloaded {count} users")

    print("\n5. Cache statistics:")
    stats = cache.get_stats()
    print(f"   Hits: {stats['cache_hits']}, Misses: {stats['cache_misses']}")
    print(f"   Hit rate: {stats['hit_rate_percent']:.1f}%")
    print(f"   Cached entries: {stats['current_entries']}")

    print("\n6. Expiration demo (TTL=5 seconds):")
    time.sleep(6)
    user_data = cache.get("user:100")
    print(f"   ✓ Entry expired: {user_data is None}")

    print("\n7. Cleanup expired entries:")
    cleaned = cache.clear_expired()
    print(f"   ✓ Cleaned {cleaned} expired entries")

    print("\n8. Different TTL per entry:")
    cache.set("short_lived", {"data": "2 second TTL"}, ttl=2)
    cache.set("long_lived", {"data": "60 second TTL"}, ttl=60)
    time.sleep(3)
    print(f"   short_lived: {cache.get('short_lived')}")
    print(f"   long_lived: {cache.get('long_lived') is not None}")

    cache.close()
    print("\n✅ Cache layer example complete!\n")


def integration_example():
    """Show how to use caching in real applications."""
    print("\n" + "=" * 80)
    print("REAL-WORLD USAGE EXAMPLES")
    print("=" * 80)

    code_example = '''
# Example 1: API endpoint with caching

from cache import CacheLayer
from fastapi import FastAPI

app = FastAPI()
cache = CacheLayer()

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    """Get user with caching."""
    # Cache-aside pattern
    user = cache.get(
        f"user:{user_id}",
        loader_fn=lambda: db.get_user(user_id),  # Your DB query
        ttl=3600  # Cache for 1 hour
    )
    return user


# Example 2: Database query caching

def get_user_with_cache(user_id: str):
    """Get user, checking cache first."""
    # Check cache
    user = cache.get(f"user:{user_id}")
    if user:
        return user

    # Load from DB
    user = db.query("SELECT * FROM users WHERE id = %s", user_id)

    # Cache for 1 hour
    cache.set(f"user:{user_id}", user, ttl=3600)

    return user


# Example 3: Warming cache on startup

def startup():
    """Warm cache with frequently accessed data."""
    config = db.get_all_config()
    cache.warm_cache(config, ttl=86400)  # Cache config for 1 day

    features = db.get_all_features()
    cache.warm_cache(features, ttl=3600)  # Cache features for 1 hour


# Example 4: Invalidating cache on writes

def update_user(user_id: str, updates: dict):
    """Update user and invalidate cache."""
    # Update database
    db.update_user(user_id, updates)

    # Invalidate cache
    cache.delete(f"user:{user_id}")

    # Optionally pre-warm with new data
    updated_user = db.get_user(user_id)
    cache.set(f"user:{user_id}", updated_user)
'''

    print(code_example)

    print("\nUse cases:")
    print("  ✓ API response caching (reduce backend load)")
    print("  ✓ Database query caching (speed up lookups)")
    print("  ✓ External API response caching (reduce API calls)")
    print("  ✓ Feature flags caching (fast feature checks)")
    print("  ✓ Configuration caching (load once, use many times)")
    print("  ✓ Computation result caching (cache expensive calculations)")


if __name__ == "__main__":
    demo_cache_layer()
    integration_example()
    print("\nCleanup: rm -rf cache_db/")
    print()
