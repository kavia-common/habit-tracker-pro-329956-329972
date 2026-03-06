"""SQLite adapter layer for the FastAPI backend.

This module isolates DB access (sqlite3) from route handlers to keep I/O concerns
out of the API layer.

Contract:
- Inputs:
  - Environment variable SQLITE_DB must be set to an absolute/relative SQLite file path.
- Outputs:
  - get_db() yields an open sqlite3.Connection with Row factory.
- Errors:
  - Raises RuntimeError with actionable context if SQLITE_DB is missing or connection fails.
- Side effects:
  - Opens/closes SQLite connections.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple


def _require_sqlite_db_path() -> str:
    """Return SQLITE_DB path or raise with actionable context."""
    db_path = os.getenv("SQLITE_DB")
    if not db_path:
        raise RuntimeError(
            "Missing required environment variable SQLITE_DB. "
            "It must point to the SQLite database file produced by the database container."
        )
    return db_path


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection configured for the app.

    - row_factory is sqlite3.Row to allow dict-like access.
    - foreign keys are enabled.
    """
    db_path = _require_sqlite_db_path()
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    except sqlite3.Error as e:
        raise RuntimeError(f"Failed to connect/query SQLite database at {db_path}: {e}") from e
    finally:
        try:
            conn.close()  # type: ignore[misc]
        except Exception:
            # Best-effort close; don't mask original exception.
            pass


def fetch_one(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    """Fetch a single row as a dict."""
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row is not None else None


def fetch_all(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    """Fetch all rows as a list of dicts."""
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def execute(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> int:
    """Execute a statement and return lastrowid (if applicable)."""
    cur = conn.execute(sql, params)
    conn.commit()
    return int(cur.lastrowid or 0)
