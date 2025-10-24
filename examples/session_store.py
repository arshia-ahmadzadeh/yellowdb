#!/usr/bin/env python3
"""Session Store: Persistent session storage for web applications.

Replace Redis/Memcached with YellowDB for managing user sessions.
Features: TTL expiration, user mapping, cleanup, statistics.
"""

import json
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from yellowdb import Batch, YellowDB


class SessionStore:
    """Persistent session storage using YellowDB."""

    def __init__(self, db_path: str = "./session_db", ttl_seconds: int = 3600):
        """Initialize session store.

        Args:
            db_path: Path to YellowDB directory.
            ttl_seconds: Session time-to-live in seconds.

        """
        self.db = YellowDB(data_directory=db_path)
        self.ttl_seconds = ttl_seconds

    def create_session(self, user_id: str, data: Dict[str, Any] = None) -> str:
        """Create a new session for user.

        Args:
            user_id: User identifier.
            data: Optional session data dictionary.

        Returns:
            Session ID.

        """
        session_id = secrets.token_urlsafe(32)
        key = f"session:{session_id}"

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat(),
            "data": data or {},
        }

        self.db.set(key, json.dumps(session_data).encode())
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data, checking expiration.

        Args:
            session_id: Session ID.

        Returns:
            Session data or None if expired.

        """
        key = f"session:{session_id}"
        session_bytes = self.db.get(key)

        if not session_bytes:
            return None

        session_data = json.loads(session_bytes.decode())
        last_accessed = datetime.fromisoformat(session_data["last_accessed"])

        if datetime.now() - last_accessed > timedelta(seconds=self.ttl_seconds):
            self.delete_session(session_id)
            return None

        session_data["last_accessed"] = datetime.now().isoformat()
        self.db.set(key, json.dumps(session_data).encode())
        return session_data

    def update_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Update session data.

        Args:
            session_id: Session ID.
            data: Data to merge into session.

        Returns:
            True if successful, False if session not found.

        """
        session_data = self.get_session(session_id)
        if not session_data:
            return False

        session_data["data"].update(data)
        session_data["last_accessed"] = datetime.now().isoformat()

        key = f"session:{session_id}"
        self.db.set(key, json.dumps(session_data).encode())
        return True

    def delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: Session ID.

        """
        self.db.delete(f"session:{session_id}")

    def get_user_sessions(self, user_id: str) -> list:
        """Get all sessions for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of session IDs.

        """
        sessions = []
        for key, value in self.db.scan(start_key="session:"):
            if not key.startswith("session:"):
                break
            session_data = json.loads(value.decode())
            if session_data["user_id"] == user_id:
                sessions.append(session_data["session_id"])
        return sessions

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions.

        Returns:
            Number of sessions cleaned up.

        """
        expired_sessions = []
        current_time = datetime.now()

        for key, value in self.db.scan(start_key="session:"):
            if not key.startswith("session:"):
                break
            session_data = json.loads(value.decode())
            last_accessed = datetime.fromisoformat(session_data["last_accessed"])

            if current_time - last_accessed > timedelta(seconds=self.ttl_seconds):
                expired_sessions.append(session_data["session_id"])

        if expired_sessions:
            with Batch(self.db) as batch:
                for session_id in expired_sessions:
                    batch.delete(f"session:{session_id}")

        return len(expired_sessions)

    def get_stats(self) -> Dict[str, Any]:
        """Get session store statistics.

        Returns:
            Dictionary with session stats.

        """
        total_sessions = sum(
            1 for key, _ in self.db.scan(start_key="session:") if key.startswith("session:")
        )
        db_stats = self.db.stats()
        return {
            "total_sessions": total_sessions,
            "memtable_size": db_stats["memtable"]["size"],
            "cache_entries": db_stats["cache"]["entries"],
        }

    def close(self) -> None:
        """Close the session store."""
        self.db.close()


def demo():
    """Demonstrate session store functionality."""
    print("\n" + "=" * 70)
    print("SESSION STORE EXAMPLE")
    print("=" * 70)

    store = SessionStore(ttl_seconds=10)

    print("\nCreating sessions:")
    session1 = store.create_session("user:100", {"ip": "192.168.1.1"})
    _ = store.create_session("user:101", {"ip": "192.168.1.2"})
    _ = store.create_session("user:100", {"ip": "10.0.0.5"})
    print("  ✓ Created 3 sessions")

    print("\nRetrieving session data:")
    session_data = store.get_session(session1)
    print(f"  User: {session_data['user_id']}")
    print(f"  Data: {session_data['data']}")

    print("\nUpdating session:")
    store.update_session(session1, {"login_count": 5, "last_page": "/dashboard"})
    updated = store.get_session(session1)
    print(f"  ✓ Updated: {updated['data']}")

    print("\nUser sessions:")
    user_sessions = store.get_user_sessions("user:100")
    print(f"  ✓ Found {len(user_sessions)} sessions for user:100")

    print("\nExpiration demo (waiting 11 seconds):")
    time.sleep(11)
    expired = store.get_session(session1)
    print(f"  ✓ Session expired: {expired is None}")

    print("\nCleanup:")
    _ = store.create_session("user:102")
    cleaned = store.cleanup_expired_sessions()
    print(f"  ✓ Cleaned {cleaned} expired sessions")

    print("\nStatistics:")
    stats = store.get_stats()
    print(f"  Total active sessions: {stats['total_sessions']}")
    print(f"  Memtable size: {stats['memtable_size']} bytes")

    store.close()
    print("\n✅ Demo complete!\n")


if __name__ == "__main__":
    demo()
