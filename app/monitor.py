import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.avito import AvitoError, fetch_listings, published_within
from app.database import Database
from app.models import Listing, Watch

log = logging.getLogger(__name__)


def listing_message(watch: Watch, listing: Listing) -> str:
    details = "\n".join(html.escape(part) for part in [listing.price, listing.location, listing.published_at] if part)
    details_block = f"\n{details}" if details else ""
    return (f"🔔 <b>Новое объявление</b>\nПоиск: <b>{html.escape(watch.name)}</b>\n\n"
            f"<b>{html.escape(listing.title)}</b>{details_block}\n\n"
            f"<a href=\"{html.escape(listing.url, quote=True)}\">Открыть на Avito</a>")


class Monitor:
    def __init__(self, database: Database, bot: Bot, poll_seconds: int = 30) -> None:
        self.db, self.bot, self.poll_seconds = database, bot, poll_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        log.info("Monitor started")
        while not self._stop.is_set():
            for watch in self.db.due_watches():
                await self.check(watch)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    async def check(self, watch: Watch) -> None:
        try:
            listings = await fetch_listings(watch.url)
            ids = [item.external_id for item in listings]
            # First successful scan creates a baseline, not a flood of historical ads.
            initial = watch.last_checked_at is None
            unseen = self.db.unseen_listing_ids(watch.id, ids)
            self.db.remember_listings(watch.id, ids)
            self.db.mark_checked(watch.id)
            if initial:
                if watch.initial_window_minutes is None:
                    log.info("Baseline saved for watch %s: %s listings", watch.id, len(ids))
                    return
                # Send every currently visible matching card that Avito marks as
                # published inside the user-selected period, then switch to new-only.
                candidates = [item for item in listings if published_within(item.published_at, watch.initial_window_minutes)]
                log.info("Initial history scan for watch %s: %s of %s listings", watch.id, len(candidates), len(listings))
            else:
                candidates = [item for item in listings if item.external_id in unseen]
            for listing in candidates:
                try:
                    await self.bot.send_message(watch.user_id, listing_message(watch, listing), parse_mode="HTML", disable_web_page_preview=True)
                except TelegramForbiddenError:
                    log.warning("User %s blocked the bot", watch.user_id)
                    break
        except AvitoError as exc:
            log.warning("Watch %s: %s", watch.id, exc)
            self.db.mark_checked(watch.id)  # do not hammer a blocked/error page
        except Exception:
            log.exception("Unexpected failure while checking watch %s", watch.id)
