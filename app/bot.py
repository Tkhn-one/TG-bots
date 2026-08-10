import html
import logging
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.avito import validate_search_url
from app.config import Settings
from app.database import Database

router = Router()


class NewWatch(StatesGroup):
    name = State()
    url = State()
    interval = State()
    delivery = State()
    custom_window = State()


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новый поиск", callback_data="new")],
        [InlineKeyboardButton(text="📋 Мои поиски", callback_data="list")],
        [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="help")],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel")]])


def watch_keyboard(watch_id: int, active: bool) -> InlineKeyboardMarkup:
    label = "⏸ Приостановить" if active else "▶️ Возобновить"
    action = "pause" if active else "resume"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"{action}:{watch_id}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{watch_id}")],
        [InlineKeyboardButton(text="← К списку", callback_data="list")],
    ])


def watches_keyboard(watches) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=("🟢 " if item.is_active else "⚪ ") + item.name[:50], callback_data=f"show:{item.id}")] for item in watches]
    rows.append([InlineKeyboardButton(text="➕ Новый поиск", callback_data="new")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def watch_text(watch) -> str:
    state = "🟢 активен" if watch.is_active else "⚪ приостановлен"
    checked = watch.last_checked_at.astimezone(UTC).strftime("%d.%m %H:%M UTC") if watch.last_checked_at else "ещё не проверялся"
    initial = "только новые после первого сканирования" if watch.initial_window_minutes is None else f"сразу прислать за последние {watch.initial_window_minutes} мин."
    return (f"<b>{html.escape(watch.name)}</b>\n\nСтатус: {state}\nИнтервал: каждые {watch.interval_minutes} мин.\nПервый запуск: {initial}\nПоследняя проверка: {checked}\n\n"
            f"<a href=\"{html.escape(watch.url, quote=True)}\">Открыть поиск на Avito</a>")


async def show_list(target: Message | CallbackQuery, db: Database, user_id: int) -> None:
    watches = db.list_watches(user_id)
    text = "<b>Мои поиски</b>\n\n" + ("Выберите поиск, чтобы посмотреть или изменить его." if watches else "Пока нет сохранённых поисков. Создайте первый — бот запомнит текущие объявления и будет присылать только новые.")
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=watches_keyboard(watches), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=watches_keyboard(watches), parse_mode="HTML")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("<b>Avito Watcher</b> следит за сохранёнными поисками и присылает новые объявления в этот чат.\n\nНастройте фильтры на Avito и сохраните ссылку на страницу результатов — это самый точный способ передать городу, категории, цене и другим условиям.", reply_markup=main_keyboard(), parse_mode="HTML")


@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def help_handler(event: Message | CallbackQuery) -> None:
    text = ("<b>Как настроить поиск</b>\n\n1. Откройте Avito в браузере.\n2. Укажите запрос, город, категорию, цену и другие фильтры.\n3. Скопируйте адрес страницы с результатами.\n4. В боте нажмите «Новый поиск» и вставьте ссылку.\n\nПервый успешный обход создаёт базу: старые объявления не отправляются. Далее придут только объявления, которых бот ещё не видел. Минимальный интервал — 5 минут.")
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← В меню", callback_data="menu")]]), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("<b>Avito Watcher</b>\nВыберите действие:", reply_markup=main_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "list")
async def list_handler(callback: CallbackQuery, db: Database) -> None:
    await show_list(callback, db, callback.from_user.id)


@router.callback_query(F.data == "new")
async def new_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewWatch.name)
    await callback.message.edit_text("<b>Новый поиск — шаг 1 из 3</b>\n\nПридумайте короткое название. Например: <i>iPhone 15 до 60k, Москва</i>.", reply_markup=cancel_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(NewWatch.name)
async def receive_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 80:
        await message.answer("Название — от 2 до 80 символов. Попробуйте ещё раз.", reply_markup=cancel_keyboard())
        return
    await state.update_data(name=name)
    await state.set_state(NewWatch.url)
    await message.answer("<b>Шаг 2 из 3</b>\n\nВставьте полную ссылку на страницу результатов поиска Avito. В ней уже должны быть настроены все нужные фильтры.", reply_markup=cancel_keyboard(), parse_mode="HTML")


@router.message(NewWatch.url)
async def receive_url(message: Message, state: FSMContext) -> None:
    try:
        url = validate_search_url(message.text or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}", reply_markup=cancel_keyboard())
        return
    await state.update_data(url=url)
    await state.set_state(NewWatch.interval)
    await message.answer("<b>Шаг 3 из 3</b>\n\nКак часто проверять поиск? Пришлите число минут: например <b>10</b>. Минимум — 5 минут. Более редкая проверка уменьшает нагрузку и риск временных ограничений со стороны Avito.", reply_markup=cancel_keyboard(), parse_mode="HTML")


@router.message(NewWatch.interval)
async def receive_interval(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    try:
        interval = int((message.text or "").strip())
        if interval < settings.min_check_interval_minutes or interval > 1440:
            raise ValueError
    except ValueError:
        await message.answer(f"Введите целое число от {settings.min_check_interval_minutes} до 1440.", reply_markup=cancel_keyboard())
        return
    await state.update_data(interval=interval)
    await state.set_state(NewWatch.delivery)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Только новые", callback_data="delivery:new")],
        [InlineKeyboardButton(text="За последний час", callback_data="delivery:60"), InlineKeyboardButton(text="За 24 часа", callback_data="delivery:1440")],
        [InlineKeyboardButton(text="За 7 дней", callback_data="delivery:10080"), InlineKeyboardButton(text="Свой период", callback_data="delivery:custom")],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel")],
    ])
    await message.answer("<b>Первый запуск</b>\n\nЧто прислать сразу после создания поиска?\n\n«Только новые» — сохранить текущую выдачу как базу и уведомлять лишь о будущих объявлениях.\n«За период» — прислать <b>все</b> подходящие объявления, которые сейчас видны в выдаче и помечены Avito как опубликованные в выбранное время; после этого бот также перейдёт в режим новых.", reply_markup=keyboard, parse_mode="HTML")


async def finish_watch_creation(message: Message, user_id: int, state: FSMContext, db: Database, monitor, initial_window_minutes: int | None) -> None:
    data = await state.get_data()
    watch_id = db.create_watch(user_id, data["name"], data["url"], data["interval"], initial_window_minutes)
    await state.clear()
    watch = db.get_watch(watch_id, user_id)
    await message.answer("⏳ Поиск сохранён. Выполняю первую проверку сейчас — ждать выбранный интервал не нужно.", reply_markup=main_keyboard())
    await monitor.check(watch)
    watch = db.get_watch(watch_id, user_id)
    await message.answer(watch_text(watch), reply_markup=watch_keyboard(watch.id, watch.is_active), parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(NewWatch.delivery, F.data.startswith("delivery:"))
async def receive_delivery(callback: CallbackQuery, state: FSMContext, db: Database, monitor) -> None:
    value = callback.data.split(":", 1)[1]
    await callback.answer()
    if value == "custom":
        await state.set_state(NewWatch.custom_window)
        await callback.message.edit_text("Введите период целым числом в минутах: от 1 до 43 200 (30 дней). Например, <b>180</b> — за последние 3 часа.", reply_markup=cancel_keyboard(), parse_mode="HTML")
        return
    await callback.message.edit_text("Настройка принята.")
    await finish_watch_creation(callback.message, callback.from_user.id, state, db, monitor, None if value == "new" else int(value))


@router.message(NewWatch.custom_window)
async def receive_custom_window(message: Message, state: FSMContext, db: Database, monitor) -> None:
    try:
        minutes = int((message.text or "").strip())
        if not 1 <= minutes <= 43200:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое число от 1 до 43 200 минут.", reply_markup=cancel_keyboard())
        return
    await finish_watch_creation(message, message.from_user.id, state, db, monitor, minutes)


@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Создание поиска отменено.", reply_markup=main_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("show:"))
async def show_watch(callback: CallbackQuery, db: Database) -> None:
    watch = db.get_watch(int(callback.data.split(":")[1]), callback.from_user.id)
    if not watch:
        await callback.answer("Поиск не найден.", show_alert=True)
        return
    await callback.message.edit_text(watch_text(watch), reply_markup=watch_keyboard(watch.id, watch.is_active), parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^(pause|resume|delete):\d+$"))
async def manage_watch(callback: CallbackQuery, db: Database) -> None:
    action, raw_id = callback.data.split(":")
    watch_id = int(raw_id)
    if action == "delete":
        db.delete_watch(watch_id, callback.from_user.id)
        await callback.answer("Поиск удалён.")
        await show_list(callback, db, callback.from_user.id)
        return
    db.set_active(watch_id, callback.from_user.id, action == "resume")
    watch = db.get_watch(watch_id, callback.from_user.id)
    if not watch:
        await callback.answer("Поиск не найден.", show_alert=True)
        return
    await callback.message.edit_text(watch_text(watch), reply_markup=watch_keyboard(watch.id, watch.is_active), parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer("Настройки сохранены.")


def create_dispatcher(db: Database, settings: Settings) -> Dispatcher:
    dp = Dispatcher()
    dp["db"] = db
    dp["settings"] = settings
    dp.include_router(router)
    return dp
