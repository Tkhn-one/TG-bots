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
