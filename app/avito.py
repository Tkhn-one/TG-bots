"""A deliberately small, replaceable client for public Avito search pages.

Markup on marketplaces changes frequently. Keep parsing isolated here so production
installations can replace it with an approved API/integration when available.
"""
import hashlib
import re
from urllib.parse import urljoin, urlparse

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
    cards = soup.select('[data-marker="item"]')
    # Older markup can omit the item wrapper, but preserves item-title.
    if not cards:
        cards = [node.parent for node in soup.select('[data-marker="item-title"]') if node.parent]

    listings: list[Listing] = []
    used: set[str] = set()
    for card in cards:
        link = card.select_one('a[data-marker="item-title"], a[itemprop="url"]')
        if not link or not link.get("href"):
            continue
        url = urljoin(BASE_URL, link["href"])
        title = link.get_text(" ", strip=True)
        if not title:
            continue
        external_id = _listing_id(url)
        if external_id in used:
            continue
        used.add(external_id)
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


def _listing_id(url: str) -> str:
    match = re.search(r"_(\d+)(?:\?|$)", url)
    return match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()
