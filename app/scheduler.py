import asyncio
import html
import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.database import Database
from app.models import Task

log = logging.getLogger(__name__)


def reminder_keyboard(task_id: int):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data=f"done:{task_id}"), InlineKeyboardButton(text="⏰ +10 мин", callback_data=f"snooze:10:{task_id}")],
        [InlineKeyboardButton(text="⏰ +1 час", callback_data=f"snooze:60:{task_id}"), InlineKeyboardButton(text="📋 Открыть задачи", callback_data="tasks")],
    ])


def reminder_text(task: Task) -> str:
    priority = {"high": "🔴 Высокий", "normal": "🟡 Обычный", "low": "🟢 Низкий"}[task.priority]
    return f"⏰ <b>Время задачи</b>\n\n<b>{html.escape(task.title)}</b>\nПриоритет: {priority}"


class Scheduler:
    def __init__(self, db: Database, bot: Bot, retention_days: int, poll_seconds: int = 20) -> None:
        self.db, self.bot, self.retention_days, self.poll_seconds = db, bot, retention_days, poll_seconds
        self._stop = asyncio.Event()
        self._cycles = 0

    async def run(self) -> None:
        log.info("Task scheduler started")
        while not self._stop.is_set():
            for task in self.db.due_tasks():
                self.db.mark_notified(task.id)
                try:
                    await self.bot.send_message(task.chat_id, reminder_text(task), parse_mode="HTML", reply_markup=reminder_keyboard(task.id))
                except TelegramForbiddenError:
                    log.warning("User %s blocked the bot", task.user_id)
                except Exception:
                    log.exception("Could not deliver reminder for task %s", task.id)
            self._cycles += 1
            if self._cycles % 4320 == 0:  # roughly once a day
                removed = self.db.cleanup_completed(self.retention_days)
                if removed:
                    log.info("Removed %s completed tasks", removed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


def next_due(task: Task) -> datetime | None:
    from datetime import timedelta
    if task.recurrence == "daily":
        return task.due_at + timedelta(days=1)
    if task.recurrence == "weekly":
        return task.due_at + timedelta(days=7)
    return None
