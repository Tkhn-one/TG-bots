import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from app.models import Watch


class Database:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def initialize(self) -> None:
        with self.connection() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL DEFAULT 10,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS seen_listings (
                    watch_id INTEGER NOT NULL,
                    external_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    PRIMARY KEY (watch_id, external_id),
                    FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_watches_active ON watches(is_active);
            """)

    def create_watch(self, user_id: int, name: str, url: str, interval: int) -> int:
        with self.connection() as con:
            cur = con.execute(
                "INSERT INTO watches(user_id, name, url, interval_minutes) VALUES (?, ?, ?, ?)",
                (user_id, name, url, interval),
            )
            return int(cur.lastrowid)

    def get_watch(self, watch_id: int, user_id: int | None = None) -> Watch | None:
        sql, args = "SELECT * FROM watches WHERE id = ?", [watch_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        with self.connection() as con:
            row = con.execute(sql, args).fetchone()
        return self._watch(row) if row else None

    def list_watches(self, user_id: int) -> list[Watch]:
        with self.connection() as con:
            rows = con.execute("SELECT * FROM watches WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
        return [self._watch(row) for row in rows]

    def due_watches(self) -> list[Watch]:
        with self.connection() as con:
            rows = con.execute("SELECT * FROM watches WHERE is_active = 1").fetchall()
        now = datetime.now(UTC)
        result = []
        for row in rows:
            watch = self._watch(row)
            if watch.last_checked_at is None or (now - watch.last_checked_at).total_seconds() >= watch.interval_minutes * 60:
                result.append(watch)
        return result

    def set_active(self, watch_id: int, user_id: int, active: bool) -> bool:
        with self.connection() as con:
            return con.execute("UPDATE watches SET is_active = ? WHERE id = ? AND user_id = ?", (active, watch_id, user_id)).rowcount > 0

    def delete_watch(self, watch_id: int, user_id: int) -> bool:
        with self.connection() as con:
            return con.execute("DELETE FROM watches WHERE id = ? AND user_id = ?", (watch_id, user_id)).rowcount > 0

    def mark_checked(self, watch_id: int) -> None:
        with self.connection() as con:
            con.execute("UPDATE watches SET last_checked_at = ? WHERE id = ?", (datetime.now(UTC).isoformat(), watch_id))

    def unseen_listing_ids(self, watch_id: int, listing_ids: list[str]) -> set[str]:
        if not listing_ids:
            return set()
        marks = ",".join("?" * len(listing_ids))
        with self.connection() as con:
            rows = con.execute(f"SELECT external_id FROM seen_listings WHERE watch_id = ? AND external_id IN ({marks})", [watch_id, *listing_ids]).fetchall()
        return set(listing_ids) - {row["external_id"] for row in rows}

    def remember_listings(self, watch_id: int, listing_ids: list[str]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connection() as con:
            con.executemany("INSERT OR IGNORE INTO seen_listings(watch_id, external_id, first_seen_at) VALUES (?, ?, ?)", [(watch_id, item, now) for item in listing_ids])

    @staticmethod
    def _watch(row: sqlite3.Row) -> Watch:
        checked = datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None
        return Watch(row["id"], row["user_id"], row["name"], row["url"], row["interval_minutes"], bool(row["is_active"]), checked)
