"""A deliberately small, replaceable client for public Avito search pages.

Markup on marketplaces changes frequently. Keep parsing isolated here so production
installations can replace it with an approved API/integration when available.
"""
import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.models import Listing

BASE_URL = "https://www.avito.ru"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AvitoWatcherBot/1.0; +https://github.com/Tkhn-one/TG-bots)",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
}


class AvitoError(RuntimeError):
    pass


def validate_search_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc not in {"avito.ru", "www.avito.ru"}:
        raise ValueError("Нужна полная HTTPS-ссылка на поиск с сайта avito.ru.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Откройте результаты поиска на Avito, настройте фильтры и пришлите ссылку на них.")
    return value


async def fetch_listings(search_url: str) -> list[Listing]:
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20.0) as client:
            response = await client.get(search_url)
        if response.status_code in {403, 429}:
            raise AvitoError("Avito временно ограничил запросы. Увеличьте интервал и повторите позже.")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AvitoError("Не удалось загрузить страницу поиска. Проверьте ссылку и интернет-соединение.") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    # Prefer the title anchor itself. On some Avito layouts an image/gallery link
    # occurs before the title inside a card; selecting a generic item URL there
    # can produce notifications such as "Ещё 10 фото" instead of a listing title.
    title_links = soup.select('a[data-marker="item-title"]')
    if not title_links:
        # Compatibility fallback for an older layout without data-marker.
        title_links = soup.select('a[itemprop="url"] h3, a[itemprop="url"]')

    listings: list[Listing] = []
    used: set[str] = set()
    for title_link in title_links:
        link = title_link if title_link.name == "a" else title_link.find_parent("a", href=True)
        if not link or not link.get("href"):
            continue
        url = urljoin(BASE_URL, link["href"])
        title = link.get_text(" ", strip=True)
        if not title or _looks_like_gallery_label(title):
            continue
        if not _matches_query(title, search_url):
            continue
        external_id = _listing_id(url)
        if external_id in used:
            continue
        used.add(external_id)
        card = _listing_container(link)
        price_node = card.select_one('[data-marker="item-price"], [itemprop="price"]')
        geo_node = card.select_one('[data-marker="item-address"], [data-marker="item-location"]')
        date_node = card.select_one('[data-marker="item-date"]')
        listings.append(Listing(
            external_id=external_id,
            title=title[:300],
            url=url,
            price=price_node.get_text(" ", strip=True) if price_node else None,
            location=geo_node.get_text(" ", strip=True) if geo_node else None,
            published_at=date_node.get_text(" ", strip=True) if date_node else None,
        ))
    if not listings and ("captcha" in response.text.lower() or "доступ ограничен" in response.text.lower()):
        raise AvitoError("Avito запросил проверку доступа. Бот не обходит CAPTCHA — попробуйте позже или используйте разрешённую интеграцию.")
    return listings


def _listing_container(link):
    """Return the closest card-like ancestor, falling back to the parent."""
    node = link
    for _ in range(8):
        parent = node.parent
        if parent is None:
            break
        node = parent
        if node.get("data-marker") == "item" or node.select_one('[data-marker="item-price"], [itemprop="price"]'):
            return node
    return link.parent


def _looks_like_gallery_label(value: str) -> bool:
    return bool(re.fullmatch(r"(?:ещё|еще)\s+\d+\s+фото", value.strip(), flags=re.IGNORECASE))


def _matches_query(title: str, search_url: str) -> bool:
    """Apply an exact local guard for the textual query in an Avito URL.

    Marketplace search can return related/recommended cards (for example, a
    different all-terrain vehicle for a `Tinger TF4` query).  A card is useful
    for this bot only when its title contains every meaningful query token.
    Category, price and geographic filters remain handled by the saved URL.
    """
    raw_query = parse_qs(urlparse(search_url).query).get("q", [""])[0]
    tokens = re.findall(r"[\wа-яё]+", raw_query.casefold(), flags=re.IGNORECASE)
    tokens = [token for token in tokens if len(token) >= 2]
    if not tokens:
        return True
    normalized_title = " ".join(re.findall(r"[\wа-яё]+", title.casefold(), flags=re.IGNORECASE))
    return all(re.search(rf"(?<!\w){re.escape(token)}(?!\w)", normalized_title) for token in tokens)


def published_within(value: str | None, window_minutes: int) -> bool:
    """Interpret the Russian publication labels used in search result cards.

    If Avito omits or changes a date label, return False rather than claiming an
    item fits a period the bot cannot verify.
    """
    if not value:
        return False
    text = " ".join(value.casefold().split())
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    if text.startswith("сегодня") or text.startswith("вчера"):
        published = now - (timedelta(days=1) if text.startswith("вчера") else timedelta())
        clock = re.search(r"(\d{1,2}):(\d{2})", text)
        if clock:
            published = published.replace(hour=int(clock.group(1)), minute=int(clock.group(2)), second=0, microsecond=0)
    else:
        relative = re.search(r"(\d+)\s+(минут[а-я]*|час[а-я]*)\s+назад", text)
        if relative:
            count, unit = int(relative.group(1)), relative.group(2)
            published = now - timedelta(minutes=count if unit.startswith("мин") else count * 60)
        else:
            months = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
                      "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
            match = re.search(r"(\d{1,2})\s+([а-я]+)", text)
            if not match or match.group(2) not in months:
                return False
            published = now.replace(month=months[match.group(2)], day=int(match.group(1)), hour=0, minute=0, second=0, microsecond=0)
            if published > now:
                published = published.replace(year=published.year - 1)
    return now - published <= timedelta(minutes=window_minutes)

def _listing_id(url: str) -> str:
    match = re.search(r"_(\d+)(?:\?|$)", url)
    return match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()
