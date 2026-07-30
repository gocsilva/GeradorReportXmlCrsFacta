from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import user_data_dir


@dataclass(frozen=True)
class IdentifierRecord:
    kind: str
    value: str
    file_hash: str
    created_at: str


class IdentifierStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (user_data_dir() / "identifiers.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._known: set[tuple[str, str]] = set()
        self._pending_writes = 0
        self._init()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init(self) -> None:
        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identifiers (
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(kind, value)
            )
            """
        )
        conn.commit()

    def exists(self, kind: str, value: str) -> bool:
        key = (kind, value)
        if key in self._known:
            return True
        row = self._connect().execute(
            "SELECT 1 FROM identifiers WHERE kind = ? AND value = ?",
            key,
        ).fetchone()
        if row is not None:
            self._known.add(key)
        return row is not None

    def add(self, kind: str, value: str, file_hash: str = "") -> None:
        self._connect().execute(
            "INSERT OR IGNORE INTO identifiers(kind, value, file_hash, created_at) VALUES (?, ?, ?, ?)",
            (kind, value, file_hash, datetime.now(timezone.utc).isoformat()),
        )
        self._pending_writes += 1
        if self._pending_writes >= 1_000:
            self.flush()
        self._known.add((kind, value))

    def clear(self) -> None:
        self._connect().execute("DELETE FROM identifiers")
        self.flush()
        self._known.clear()

    def flush(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._pending_writes = 0

    def close(self) -> None:
        if self._conn is not None:
            self.flush()
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
