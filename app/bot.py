import html
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database import Database
from app.models import Task
from app.scheduler import next_due, reminder_keyboard, reminder_text

router = Router()


class NewTask(StatesGroup):
    title = State()
    custom_date = State()
    priority = State()
    recurrence = State()


class SettingsState(StatesGroup):
    timezone = State()


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новая задача", callback_data="new")],
        [InlineKeyboardButton(text="📋 Мои задачи", callback_data="tasks")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"), InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ])


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel")]])


def task_keyboard(task: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data=f"done:{task.id}"), InlineKeyboardButton(text="⏰ +10 мин", callback_data=f"snooze:10:{task.id}")],
        [InlineKeyboardButton(text="⏰ +1 час", callback_data=f"snooze:60:{task.id}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{task.id}")],
        [InlineKeyboardButton(text="← К списку", callback_data="tasks")],
    ])


def format_due(task: Task, timezone: str) -> str:
    return task.due_at.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y в %H:%M")


def task_text(task: Task, timezone: str) -> str:
    priority = {"high": "🔴 высокий", "normal": "🟡 обычный", "low": "🟢 низкий"}[task.priority]
    recurrence = {None: "нет", "daily": "каждый день", "weekly": "каждую неделю"}[task.recurrence]
    return f"<b>{html.escape(task.title)}</b>\n\n📅 {format_due(task, timezone)}\nПриоритет: {priority}\nПовтор: {recurrence}"


async def show_tasks(target: Message | CallbackQuery, db: Database, user_id: int) -> None:
    timezone = db.timezone(user_id)
    tasks = db.tasks_for_user(user_id)
    if not tasks:
        text, keyboard = "<b>Нет активных задач</b>\n\nДобавьте первую задачу — бот напомнит о ней вовремя.", menu()
    else:
        now = datetime.now(UTC)
        rows = []
        for task in tasks:
            icon = "🔴" if task.due_at < now else "•"
            rows.append([InlineKeyboardButton(text=f"{icon} {task.title[:36]} — {format_due(task, timezone)[0:11]}", callback_data=f"show:{task.id}")])
        rows.append([InlineKeyboardButton(text="➕ Новая задача", callback_data="new"), InlineKeyboardButton(text="🏠 Меню", callback_data="menu")])
        text, keyboard = f"<b>Мои задачи</b>\nАктивных: {len(tasks)}", InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear(); db.ensure_user(message.from_user.id)
    await message.answer("<b>FocusFlow</b> — простой планировщик задач и напоминаний.\n\nДобавьте задачу, выберите срок — в нужное время я пришлю напоминание с кнопками «Готово» и «Отложить».", reply_markup=menu(), parse_mode="HTML")


@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def help_handler(event: Message | CallbackQuery) -> None:
    text = "<b>Как пользоваться</b>\n\n1. Нажмите «Новая задача».\n2. Напишите, что нужно сделать.\n3. Выберите срок, приоритет и повтор.\n4. В момент дедлайна придёт напоминание. Его можно завершить или отложить на 10 минут / час.\n\nКоманды: /start — меню, /tasks — список задач."
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Меню", callback_data="menu")]]), parse_mode="HTML"); await event.answer()
    else: await event.answer(text, reply_markup=menu(), parse_mode="HTML")


@router.message(Command("tasks"))
async def tasks_command(message: Message, db: Database) -> None:
    await show_tasks(message, db, message.from_user.id)


@router.callback_query(F.data == "menu")
async def menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear(); await callback.message.edit_text("<b>FocusFlow</b>\nВыберите действие:", reply_markup=menu(), parse_mode="HTML"); await callback.answer()


@router.callback_query(F.data == "tasks")
async def tasks_handler(callback: CallbackQuery, db: Database) -> None:
    await show_tasks(callback, db, callback.from_user.id)


@router.callback_query(F.data == "new")
async def new_task(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewTask.title)
    await callback.message.edit_text("<b>Новая задача — шаг 1 из 4</b>\n\nНапишите, что нужно сделать. Например: <i>Позвонить в сервис</i>.", reply_markup=cancel(), parse_mode="HTML"); await callback.answer()


@router.message(NewTask.title)
async def receive_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not 2 <= len(title) <= 300:
        await message.answer("Задача должна содержать от 2 до 300 символов.", reply_markup=cancel()); return
    await state.update_data(title=title)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Через 15 минут", callback_data="due:15"), InlineKeyboardButton(text="Через 1 час", callback_data="due:60")],
        [InlineKeyboardButton(text="Сегодня в 19:00", callback_data="due:evening"), InlineKeyboardButton(text="Завтра в 09:00", callback_data="due:tomorrow")],
        [InlineKeyboardButton(text="Свои дата и время", callback_data="due:custom")], [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
    ])
    await message.answer("<b>Шаг 2 из 4</b>\n\nКогда напомнить?", reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(NewTask.title, F.data.startswith("due:"))
async def receive_due(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    value = callback.data.split(":", 1)[1]
    timezone = ZoneInfo(db.timezone(callback.from_user.id)); now = datetime.now(timezone)
    if value == "custom":
        await state.set_state(NewTask.custom_date); await callback.message.edit_text("Введите дату и время в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>. Например: <b>28.08.2026 14:30</b>.", reply_markup=cancel(), parse_mode="HTML"); await callback.answer(); return
    if value.isdigit(): due = now + timedelta(minutes=int(value))
    elif value == "evening":
        due = now.replace(hour=19, minute=0, second=0, microsecond=0)
        if due <= now: due += timedelta(days=1)
    else:
        due = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    await state.update_data(due_at=due.isoformat()); await ask_priority(callback.message, state); await callback.answer()


@router.message(NewTask.custom_date)
async def receive_custom_due(message: Message, state: FSMContext, db: Database) -> None:
    try:
        due = datetime.strptime((message.text or "").strip(), "%d.%m.%Y %H:%M").replace(tzinfo=ZoneInfo(db.timezone(message.from_user.id)))
        if due <= datetime.now(ZoneInfo(db.timezone(message.from_user.id))): raise ValueError
    except ValueError:
        await message.answer("Не получилось. Используйте будущую дату в формате ДД.ММ.ГГГГ ЧЧ:ММ.", reply_markup=cancel()); return
    await state.update_data(due_at=due.isoformat()); await ask_priority(message, state)


async def ask_priority(message: Message, state: FSMContext) -> None:
    await state.set_state(NewTask.priority)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔴 Высокий", callback_data="priority:high"), InlineKeyboardButton(text="🟡 Обычный", callback_data="priority:normal"), InlineKeyboardButton(text="🟢 Низкий", callback_data="priority:low")], [InlineKeyboardButton(text="Отмена", callback_data="cancel")]])
    await message.answer("<b>Шаг 3 из 4</b>\n\nВыберите приоритет.", reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(NewTask.priority, F.data.startswith("priority:"))
async def receive_priority(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(priority=callback.data.split(":", 1)[1]); await state.set_state(NewTask.recurrence)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Без повтора", callback_data="repeat:none"), InlineKeyboardButton(text="Каждый день", callback_data="repeat:daily"), InlineKeyboardButton(text="Каждую неделю", callback_data="repeat:weekly")], [InlineKeyboardButton(text="Отмена", callback_data="cancel")]])
    await callback.message.edit_text("<b>Шаг 4 из 4</b>\n\nНужно повторять задачу?", reply_markup=keyboard, parse_mode="HTML"); await callback.answer()


@router.callback_query(NewTask.recurrence, F.data.startswith("repeat:"))
async def receive_recurrence(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    recurrence = callback.data.split(":", 1)[1]; data = await state.get_data()
    task_id = db.create_task(callback.from_user.id, callback.message.chat.id, data["title"], datetime.fromisoformat(data["due_at"]), data["priority"], None if recurrence == "none" else recurrence)
    await state.clear(); task = db.get_task(task_id, callback.from_user.id); timezone = db.timezone(callback.from_user.id)
    await callback.message.edit_text("✅ Задача сохранена.", reply_markup=menu()); await callback.message.answer(task_text(task, timezone), reply_markup=task_keyboard(task), parse_mode="HTML"); await callback.answer()


@router.callback_query(F.data == "settings")
async def settings(callback: CallbackQuery, db: Database) -> None:
    timezone = db.timezone(callback.from_user.id)
    await callback.message.edit_text(f"<b>Настройки</b>\n\nЧасовой пояс: <b>{timezone}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Изменить часовой пояс", callback_data="timezone")], [InlineKeyboardButton(text="← Меню", callback_data="menu")]]), parse_mode="HTML"); await callback.answer()


@router.callback_query(F.data == "timezone")
async def timezone_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsState.timezone); await callback.message.edit_text("Введите IANA-часовой пояс, например <b>Europe/Moscow</b>, <b>Europe/London</b> или <b>Asia/Yekaterinburg</b>.", reply_markup=cancel(), parse_mode="HTML"); await callback.answer()


@router.message(SettingsState.timezone)
async def set_timezone(message: Message, state: FSMContext, db: Database) -> None:
    value = (message.text or "").strip()
    try: ZoneInfo(value)
    except ZoneInfoNotFoundError: await message.answer("Неизвестный пояс. Используйте формат вроде Europe/Moscow.", reply_markup=cancel()); return
    db.set_timezone(message.from_user.id, value); await state.clear(); await message.answer(f"✅ Часовой пояс установлен: <b>{html.escape(value)}</b>", reply_markup=menu(), parse_mode="HTML")


@router.callback_query(F.data.startswith("show:"))
async def show_task(callback: CallbackQuery, db: Database) -> None:
    task = db.get_task(int(callback.data.split(":")[1]), callback.from_user.id)
    if not task: await callback.answer("Задача не найдена.", show_alert=True); return
    await callback.message.edit_text(task_text(task, db.timezone(callback.from_user.id)), reply_markup=task_keyboard(task), parse_mode="HTML"); await callback.answer()


@router.callback_query(F.data.regexp(r"^(done|delete):\d+$"))
async def task_action(callback: CallbackQuery, db: Database) -> None:
    action, raw_id = callback.data.split(":"); task_id = int(raw_id)
    if action == "delete":
        db.delete_task(task_id, callback.from_user.id); await callback.answer("Задача удалена."); await show_tasks(callback, db, callback.from_user.id); return
    task = db.complete(task_id, callback.from_user.id)
    if not task: await callback.answer("Задача уже недоступна.", show_alert=True); return
    due = next_due(task)
    if due: db.create_task(task.user_id, task.chat_id, task.title, due, task.priority, task.recurrence)
    await callback.message.edit_text("✅ Готово" + (". Следующее повторение создано." if due else ".")); await callback.answer()


@router.callback_query(F.data.regexp(r"^snooze:(10|60):\d+$"))
async def snooze(callback: CallbackQuery, db: Database) -> None:
    _, minutes, raw_id = callback.data.split(":"); task = db.snooze(int(raw_id), callback.from_user.id, int(minutes))
    if not task: await callback.answer("Задача уже недоступна.", show_alert=True); return
    await callback.message.edit_text(f"⏰ Напомню через {minutes} мин."); await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear(); await callback.message.edit_text("Действие отменено.", reply_markup=menu()); await callback.answer()


def create_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher(); dp["db"] = db; dp.include_router(router); return dp
