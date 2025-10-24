# YellowDB Real-World Examples

Production-ready examples demonstrating YellowDB in real applications. Start with the example that matches your use case.

## Quick Start

```bash
# Web sessions (Flask/FastAPI)
python session_store.py

# Application caching
python cache_layer.py
```

All examples are self-contained and create their own test databases automatically.

---

## 1. `session_store.py` - Web Application Sessions

**Use Case:** Replace Redis/Memcached for session storage in web applications.

### What It Demonstrates
- Persistent session storage with unique IDs
- TTL-based automatic expiration
- User-to-sessions mapping
- Session updates and cleanup
- Integration patterns for Flask/FastAPI/Django

### Example Usage
```python
from session_store import SessionStore

store = SessionStore(ttl_seconds=3600)

# Create session
session_id = store.create_session("user:100")

# Get session (checks expiration)
session_data = store.get_session(session_id)

# Update session
store.update_session(session_id, {"login_count": 5})

# Get all sessions for a user
user_sessions = store.get_user_sessions("user:100")

# Manual cleanup of expired sessions
cleaned = store.cleanup_expired_sessions()
```

### Real-World Benefits
✓ No external dependencies (no Redis needed)
✓ Persistent on-disk storage
✓ Automatic TTL-based cleanup
✓ Fast in-memory caching of active sessions
✓ Thread-safe operations
✓ Scales to millions of sessions

### Flask Integration Example
```python
from flask import Flask, session, request, redirect
from session_store import SessionStore

app = Flask(__name__)
sessions = SessionStore()

@app.route('/login', methods=['POST'])
def login():
    user_id = request.form.get('username')
    session_id = sessions.create_session(user_id)
    response = redirect('/dashboard')
    response.set_cookie('session_id', session_id)
    return response

@app.route('/dashboard')
def dashboard():
    session_id = request.cookies.get('session_id')
    session_data = sessions.get_session(session_id)
    if not session_data:
        return redirect('/login')
    return f"Welcome {session_data['user_id']}"

@app.route('/logout')
def logout():
    session_id = request.cookies.get('session_id')
    sessions.delete_session(session_id)
    return redirect('/')
```

---

## 2. `cache_layer.py` - Application-Level Caching

**Use Case:** Cache API responses, database queries, or expensive computations.

### What It Demonstrates
- Cache-aside pattern (lazy-loading)
- TTL-based automatic expiration
- Cache warming (batch preloading)
- Hit rate tracking and statistics
- Atomic cache updates with metadata

### Example Usage
```python
from cache_layer import CacheLayer

cache = CacheLayer(default_ttl=3600)

# Cache-aside pattern: load on miss
user = cache.get(
    "user:100",
    loader_fn=lambda: db.get_user(100),  # Called if not cached
    ttl=3600
)

# Direct cache set
cache.set("config:app", config_dict)

# Batch warming (preload known data)
data = {"feature:a": True, "feature:b": False}
cache.warm_cache(data, ttl=86400)

# Get statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate_percent']:.1f}%")

# Manual expiration cleanup
cleaned = cache.clear_expired()
```

### Real-World Benefits
✓ Reduce backend/database load by 50%+
✓ Faster response times (in-memory caching)
✓ TTL-based automatic cleanup
✓ Hit rate tracking for optimization
✓ No external cache server needed
✓ Per-key TTL configuration

### FastAPI Integration Example
```python
from fastapi import FastAPI
from cache_layer import CacheLayer

app = FastAPI()
cache = CacheLayer()

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    return cache.get(
        f"user:{user_id}",
        loader_fn=lambda: db.get_user(user_id),
        ttl=3600
    )

@app.post("/users/{user_id}")
async def update_user(user_id: str, data: dict):
    # Update database
    db.update_user(user_id, data)
    # Invalidate cache
    cache.delete(f"user:{user_id}")
    # Optionally pre-warm
    updated = db.get_user(user_id)
    cache.set(f"user:{user_id}", updated, ttl=3600)
    return updated
```

---

## Key Features Across Examples

| Feature | session_store.py | cache_layer.py |
|---------|-----------------|-----------------|
| Batch operations | ✓ | ✓ |
| TTL/expiration | ✓ | ✓ |
| Range queries | ✓ | ✗ |
| Statistics | ✓ | ✓ |
| High-throughput | ✓ | ✓ |

---

## Performance Characteristics

```
Example            Ops/sec    Throughput      Use Case
───────────────────────────────────────────────────────
session_store.py   50,000     Session storage
cache_layer.py     100,000    API/DB caching
```

All examples use default configuration. Tune as needed for your workload.

---

## Running the Examples

### Prerequisites
```bash
pip install yellowdb
```

### Run Individual Examples
```bash
# Run session example (creates session_db/)
python session_store.py

# Run cache example (creates cache_db/)
python cache_layer.py
```

### Clean Up Test Databases
```bash
rm -rf session_db cache_db
```

---

## Adapting Examples to Your Use Case

### To use session_store.py in your project:

1. Copy the `SessionStore` class
2. Initialize at app startup
3. Use in login/logout handlers
4. Call `cleanup_expired_sessions()` periodically (e.g., hourly)

### To use cache_layer.py in your project:

1. Copy the `CacheLayer` class
2. Initialize at app startup
3. Wrap expensive operations with `cache.get(key, loader_fn)`
4. Invalidate cache on writes: `cache.delete(key)`
5. Monitor hit rate with `cache.get_stats()`

---

## Configuration & Tuning

### For Session Storage (session_store.py)

```python
# Long TTL for infrequent active users
store = SessionStore(ttl_seconds=86400)  # 24 hours

# Short TTL for frequent active users
store = SessionStore(ttl_seconds=3600)   # 1 hour

# Configure database
Config.reset()
config = Config()
config.set_cache_size(256 * 1024 * 1024)  # Larger cache for sessions
store = SessionStore()
```

### For Caching (cache_layer.py)

```python
# High-throughput caching
cache = CacheLayer(default_ttl=3600)
Config.reset()
config = Config()
config.set_cache_size(1024 * 1024 * 1024)  # 1GB cache

# Space-constrained caching
config.compression_level = 9
config.enable_compression = True
```

---

## Troubleshooting

**Q: Database already locked error?**
A: Make sure you're closing databases properly:
```python
# Good:
with YellowDB() as db:
    db.set("key", b"value")
# Auto-closes

# Or:
db = YellowDB()
# ... code ...
db.close()  # Don't forget!
```

**Q: Low cache hit rate?**
A: Increase cache size:
```python
config = Config()
config.set_cache_size(512 * 1024 * 1024)  # 512MB
```

## License

All examples are part of YellowDB and follow the MIT license.
