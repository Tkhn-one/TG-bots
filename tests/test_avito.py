from bs4 import BeautifulSoup

from app.avito import _looks_like_gallery_label, _matches_query, _listing_container


def test_query_guard_rejects_unrelated_recommended_listing() -> None:
    url = "https://www.avito.ru/moskva/vezdehody?q=Tinger+TF4"
    assert _matches_query("Tinger TF4, 2026, 1 км", url)
    assert not _matches_query("Асгард Standart, 2026, 5 км", url)


def test_query_guard_allows_filter_only_urls() -> None:
    assert _matches_query("Асгард Standart", "https://www.avito.ru/moskva/vezdehody?cd=1")


def test_gallery_label_is_not_a_listing_title() -> None:
    assert _looks_like_gallery_label("Ещё 10 фото")
    assert _looks_like_gallery_label("Еще 1 фото")
    assert not _looks_like_gallery_label("Tinger TF4")


def test_container_is_scoped_to_title_card() -> None:
    soup = BeautifulSoup('''<div data-marker="item"><a data-marker="item-title" href="/x">Tinger TF4</a><span data-marker="item-price">220 000 ₽</span></div>''', "html.parser")
    link = soup.select_one('a[data-marker="item-title"]')
    assert _listing_container(link).get("data-marker") == "item"

from app.avito import published_within


def test_recent_publication_labels() -> None:
    assert published_within("Сегодня в 12:00", 24 * 60)
    assert published_within("30 минут назад", 31)
    assert not published_within("30 минут назад", 29)
    assert not published_within(None, 60)


def test_seen_listing_retention_keeps_newest_entries(tmp_path) -> None:
    from app.database import Database

    db = Database(str(tmp_path / "watch.sqlite3"))
    db.initialize()
    watch_id = db.create_watch(1, "test", "https://www.avito.ru/moskva?q=test", 5)
    db.remember_listings(watch_id, [str(number) for number in range(6)])
    assert db.prune_seen_listings(watch_id, max_count=3, retention_days=365) == 3
    assert db.unseen_listing_ids(watch_id, ["0", "1", "2", "3", "4", "5"]) == {"0", "1", "2"}
