import asyncio

from db.models import Article
from handlers import draft_make


def test_ensure_tax_article_image_upgrades_preview(monkeypatch):
    article = Article(
        id=1,
        title="Новина",
        url="https://tax.gov.ua/media-tsentr/novini/947477.html",
        source_domain="tax.gov.ua",
        summary="",
        image_url="https://tax.gov.ua/data/material/000/813/947477/preview1.jpg",
        level1_ok=True,
    )

    expected = "https://tax.gov.ua/data/material/000/813/947477/6900d1880b6df.jpg"

    async def fake_fetch(url: str) -> str:
        assert url == article.url
        return "<html><body><img src=\"/data/material/000/813/947477/preview1.jpg\" /></body></html>"

    def fake_extract(html: str, base_url: str | None = None) -> str:
        return article.image_url

    def fake_prefer(html: str, *, base_url: str | None, fallback: str | None) -> str:
        assert fallback == article.image_url
        return expected

    monkeypatch.setattr(draft_make, "staged_fetch_html", fake_fetch)
    monkeypatch.setattr(draft_make, "extract_image", fake_extract)
    monkeypatch.setattr(draft_make, "prefer_tax_article_image", fake_prefer)

    result = asyncio.run(draft_make._ensure_tax_article_image(article))

    assert result == expected
    assert article.image_url == expected


def test_ensure_tax_article_image_skips_when_already_full(monkeypatch):
    article = Article(
        id=2,
        title="Новина",
        url="https://tax.gov.ua/media-tsentr/novini/947478.html",
        source_domain="tax.gov.ua",
        summary="",
        image_url="https://tax.gov.ua/data/material/000/813/947478/full.jpg",
        level1_ok=True,
    )

    called = False

    async def fake_fetch(url: str) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(draft_make, "staged_fetch_html", fake_fetch)

    result = asyncio.run(draft_make._ensure_tax_article_image(article))

    assert result == article.image_url
    assert not called


def test_ensure_tax_article_image_uses_extract_fallback(monkeypatch):
    article = Article(
        id=3,
        title="Новина",
        url="https://tax.gov.ua/media-tsentr/novini/947479.html",
        source_domain="tax.gov.ua",
        summary="",
        image_url="https://tax.gov.ua/data/material/000/813/947479/preview1.jpg",
        level1_ok=True,
    )

    fallback = "https://tax.gov.ua/data/material/000/813/947479/full.jpg"

    async def fake_fetch(url: str) -> str:
        return "<html><body></body></html>"

    def fake_extract(html: str, base_url: str | None = None) -> str:
        return fallback

    def fake_prefer(html: str, *, base_url: str | None, fallback: str | None) -> str | None:
        return None

    monkeypatch.setattr(draft_make, "staged_fetch_html", fake_fetch)
    monkeypatch.setattr(draft_make, "extract_image", fake_extract)
    monkeypatch.setattr(draft_make, "prefer_tax_article_image", fake_prefer)

    result = asyncio.run(draft_make._ensure_tax_article_image(article))

    assert result == fallback
    assert article.image_url == fallback
