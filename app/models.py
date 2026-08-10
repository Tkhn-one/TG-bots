from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Task:
    id: int
    user_id: int
    chat_id: int
    title: str
    due_at: datetime
    priority: str
    recurrence: str | None
    is_done: bool
    notified_at: datetime | None
    created_at: datetime
