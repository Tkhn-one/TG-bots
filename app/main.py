import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

from app.bot import create_dispatcher
from app.config import get_settings
from app.database import Database
from app.monitor import Monitor


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(settings.database_path)
    db.initialize()
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else AiohttpSession()
    bot = Bot(settings.bot_token, session=session)
    monitor = Monitor(db, bot, max_seen_per_watch=settings.max_seen_listings_per_watch, seen_retention_days=settings.seen_listing_retention_days)
    monitor_task = asyncio.create_task(monitor.run())
    dp = create_dispatcher(db, settings)
    dp["monitor"] = monitor
    try:
        # A lost connection should not require manual restart of a deployed bot.
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False)
                break
            except TelegramNetworkError as exc:
                logging.getLogger(__name__).warning(
                    "Telegram Bot API is unavailable (%s). Retrying in 30 seconds. "
                    "Check network access, firewall, VPN or TELEGRAM_PROXY.", exc
                )
                await asyncio.sleep(30)
    finally:
        monitor.stop()
        await monitor_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
