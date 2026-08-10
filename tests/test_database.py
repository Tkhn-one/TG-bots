from datetime import UTC, datetime, timedelta

from app.database import Database


def test_task_lifecycle(tmp_path):
    db = Database(str(tmp_path / "tasks.sqlite3")); db.initialize()
    due = datetime.now(UTC) - timedelta(minutes=1)
    task_id = db.create_task(1, 1, "Проверить задачу", due, "high", None)
    assert [task.id for task in db.due_tasks()] == [task_id]
    db.mark_notified(task_id)
    assert db.due_tasks() == []
    task = db.snooze(task_id, 1, 10)
    assert task and task.notified_at is None and task.due_at > datetime.now(UTC)
    assert db.complete(task_id, 1)
    assert db.tasks_for_user(1) == []


def test_user_timezone(tmp_path):
    db = Database(str(tmp_path / "tasks.sqlite3")); db.initialize()
    assert db.timezone(42) == "Europe/Moscow"
    db.set_timezone(42, "Europe/London")
    assert db.timezone(42) == "Europe/London"
