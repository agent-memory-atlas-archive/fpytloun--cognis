"""Disk-backed, bounded-cache inventory for one S3 retention pass."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple


class RetentionPair(NamedTuple):
    """Only metadata needed for deletion; never a tool output payload."""

    key: str
    text_size: int
    anchor_size: int


class RetentionInventory:
    """Spill listing metadata instead of retaining SDK object graphs in RAM."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, key: str, *, text: bool, size: int, modified: float) -> None:
        """Preserve first-seen ordering and prefer the text object's timestamp."""
        self.connection.execute(
            """INSERT INTO pairs
               (key, text_size, anchor_size, modified, text_time)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   text_size = text_size + excluded.text_size,
                   anchor_size = anchor_size + excluded.anchor_size,
                   modified = CASE WHEN excluded.text_time IS NOT NULL
                                   THEN excluded.modified ELSE modified END,
                   text_time = COALESCE(excluded.text_time, text_time)""",
            (key, size if text else 0, 0 if text else size, modified, modified if text else None),
        )

    def finish(self) -> int:
        """Complete the entire inventory before permitting external deletion."""
        self.connection.execute("CREATE INDEX retention_order ON pairs(modified)")
        self.connection.commit()
        return int(
            self.connection.execute(
                "SELECT COALESCE(SUM(text_size + anchor_size), 0) FROM pairs"
            ).fetchone()[0]
        )

    def candidates(
        self, *, expired_before: float | None = None
    ) -> Generator[RetentionPair, None, None]:
        """Yield ordered candidates without materializing all pairs or SDK metadata."""
        query = "SELECT key, text_size, anchor_size FROM pairs WHERE skipped = 0"
        args: tuple[float, ...] = ()
        if expired_before is not None:
            query += " AND text_time < ?"
            args = (expired_before,)
        query += " ORDER BY modified, rowid"
        cursor = self.connection.execute(query, args)
        try:
            for row in cursor:
                yield RetentionPair(*row)
        finally:
            cursor.close()

    def skip(self, key: str) -> None:
        """Exclude deleted or failed pairs from later phases of this pass."""
        self.connection.execute("UPDATE pairs SET skipped = 1 WHERE key = ?", (key,))


@contextmanager
def retention_inventory() -> Iterator[RetentionInventory]:
    """Own scratch files and SQLite lifetime entirely inside the maintenance worker."""
    with TemporaryDirectory(prefix="cognis-retention-") as directory:
        connection = sqlite3.connect(Path(directory) / "inventory.sqlite")
        try:
            # Disposable metadata, not durable application state. Cache and sort
            # storage must not scale Python heap with the bucket's object count.
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA cache_size=-1024")
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute("PRAGMA mmap_size=0")
            connection.execute(
                """CREATE TABLE pairs (
                    key TEXT UNIQUE NOT NULL,
                    text_size INTEGER NOT NULL,
                    anchor_size INTEGER NOT NULL,
                    modified REAL NOT NULL,
                    text_time REAL,
                    skipped INTEGER NOT NULL DEFAULT 0
                )"""
            )
            yield RetentionInventory(connection)
        finally:
            connection.close()
