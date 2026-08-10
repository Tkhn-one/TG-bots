import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from app.models import Task


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
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    timezone TEXT NOT NULL DEFAULT 'Europe/Moscow'
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    recurrence TEXT,
                    is_done INTEGER NOT NULL DEFAULT 0,
                    notified_at TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(is_done, due_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, is_done, due_at);
            """)

    def ensure_user(self, user_id: int) -> None:
        with self.connection() as con:
            con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))

    def timezone(self, user_id: int) -> str:
        self.ensure_user(user_id)
        with self.connection() as con:
            return con.execute("SELECT timezone FROM users WHERE user_id = ?", (user_id,)).fetchone()["timezone"]

    def set_timezone(self, user_id: int, timezone: str) -> None:
        with self.connection() as con:
            con.execute("INSERT INTO users(user_id, timezone) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone", (user_id, timezone))

    def create_task(self, user_id: int, chat_id: int, title: str, due_at: datetime, priority: str, recurrence: str | None) -> int:
        now = datetime.now(UTC).isoformat()
        with self.connection() as con:
            cur = con.execute("INSERT INTO tasks(user_id, chat_id, title, due_at, priority, recurrence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, chat_id, title, due_at.astimezone(UTC).isoformat(), priority, recurrence, now))
            return int(cur.lastrowid)

    def get_task(self, task_id: int, user_id: int | None = None) -> Task | None:
        query, args = "SELECT * FROM tasks WHERE id = ?", [task_id]
        if user_id is not None:
            query += " AND user_id = ?"; args.append(user_id)
        with self.connection() as con:
            row = con.execute(query, args).fetchone()
        return self._task(row) if row else None

    def tasks_for_user(self, user_id: int, limit: int = 30) -> list[Task]:
        with self.connection() as con:
            rows = con.execute("SELECT * FROM tasks WHERE user_id = ? AND is_done = 0 ORDER BY due_at LIMIT ?", (user_id, limit)).fetchall()
        return [self._task(row) for row in rows]

    def due_tasks(self) -> list[Task]:
        now = datetime.now(UTC).isoformat()
        with self.connection() as con:
            rows = con.execute("SELECT * FROM tasks WHERE is_done = 0 AND notified_at IS NULL AND due_at <= ? ORDER BY due_at", (now,)).fetchall()
        return [self._task(row) for row in rows]

    def mark_notified(self, task_id: int) -> None:
        with self.connection() as con:
            con.execute("UPDATE tasks SET notified_at = ? WHERE id = ?", (datetime.now(UTC).isoformat(), task_id))

    def complete(self, task_id: int, user_id: int) -> Task | None:
        task = self.get_task(task_id, user_id)
        if not task or task.is_done:
            return None
        with self.connection() as con:
            con.execute("UPDATE tasks SET is_done = 1, completed_at = ? WHERE id = ? AND user_id = ?", (datetime.now(UTC).isoformat(), task_id, user_id))
        return task

    def snooze(self, task_id: int, user_id: int, minutes: int) -> Task | None:
        task = self.get_task(task_id, user_id)
        if not task or task.is_done:
            return None
        due = datetime.now(UTC) + timedelta(minutes=minutes)
        with self.connection() as con:
            con.execute("UPDATE tasks SET due_at = ?, notified_at = NULL WHERE id = ? AND user_id = ?", (due.isoformat(), task_id, user_id))
        return self.get_task(task_id, user_id)

    def delete_task(self, task_id: int, user_id: int) -> bool:
        with self.connection() as con:
            return con.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)).rowcount > 0

    def cleanup_completed(self, retention_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self.connection() as con:
            return con.execute("DELETE FROM tasks WHERE is_done = 1 AND completed_at < ?", (cutoff,)).rowcount

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(row["id"], row["user_id"], row["chat_id"], row["title"], datetime.fromisoformat(row["due_at"]), row["priority"], row["recurrence"], bool(row["is_done"]), datetime.fromisoformat(row["notified_at"]) if row["notified_at"] else None, datetime.fromisoformat(row["created_at"]))
