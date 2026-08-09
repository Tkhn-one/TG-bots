import asyncio
import logging

from aiogram import Bot

from app.bot import create_dispatcher
from app.config import get_settings
from app.database import Database
from app.monitor import Monitor


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(settings.database_path)
    db.initialize()
    bot = Bot(settings.bot_token)
    monitor = Monitor(db, bot)
    monitor_task = asyncio.create_task(monitor.run())
    dp = create_dispatcher(db, settings)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        monitor.stop()
        await monitor_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
