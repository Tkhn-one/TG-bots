import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

from app.bot import create_dispatcher
from app.config import get_settings
from app.database import Database
from app.scheduler import Scheduler


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(settings.task_database_path); db.initialize()
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else AiohttpSession()
    bot = Bot(settings.bot_token, session=session)
    scheduler = Scheduler(db, bot, settings.completed_task_retention_days)
    scheduler_task = asyncio.create_task(scheduler.run())
    dp = create_dispatcher(db)
    try:
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False)
                break
            except TelegramNetworkError as exc:
                logging.getLogger(__name__).warning("Telegram Bot API is unavailable (%s). Retrying in 30 seconds.", exc)
                await asyncio.sleep(30)
    finally:
        scheduler.stop(); await scheduler_task; await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
