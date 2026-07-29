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
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init(self) -> None:
        with self._connect() as conn:
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

    def exists(self, kind: str, value: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM identifiers WHERE kind = ? AND value = ?",
                (kind, value),
            ).fetchone()
        return row is not None

    def add(self, kind: str, value: str, file_hash: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO identifiers(kind, value, file_hash, created_at) VALUES (?, ?, ?, ?)",
                (kind, value, file_hash, datetime.now(timezone.utc).isoformat()),
            )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM identifiers")
