from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import asyncio
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from jobs.nbu_scraper import (
    NBUNewsItem,
    NBU_ALL_NEWS_URL,
    NBU_NEWS_URL,
    NBU_SEARCH_URL,
    fetch_nbu_news,
    parse_nbu_news,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nbu_news.html"
KYIV_TZ = ZoneInfo("Europe/Kyiv")
REFERENCE_NOW = datetime(2025, 10, 23, 12, 0, tzinfo=KYIV_TZ)


def test_parse_nbu_news_returns_items():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    items = parse_nbu_news(html, now=REFERENCE_NOW)

    assert len(items) == 7
    first = items[0]
    assert isinstance(first, NBUNewsItem)
    assert first.title == "НБУ запровадив новий стандарт звітності"
    assert first.url == "https://bank.gov.ua/ua/news/news/perviy-zapys"
    assert first.summary.startswith("Національний банк України")
    assert first.published == datetime(2024, 8, 15, 7, 30, tzinfo=timezone.utc)

    second = items[1]
    assert second.title == "Оновлено порядок ліцензування"
    assert second.url == "https://bank.gov.ua/ua/news/news/drugiy-zapys"
    assert second.summary == "Роз'яснення щодо подання документів до НБУ."
    assert second.published == datetime(2024, 9, 1, 6, 5, tzinfo=timezone.utc)

    third = items[2]
    assert third.title == "НБУ оприлюднив аналітику"
    assert third.url == "https://bank.gov.ua/ua/news/all-news/shhe-odin-zapys"
    assert third.summary == "У фокусі – нові макроекономічні показники."
    assert third.published == datetime(2024, 9, 5, 11, 10, tzinfo=timezone.utc)

    fourth = items[3]
    assert fourth.title == "Старе повідомлення"
    assert fourth.published == datetime(2023, 5, 19, 21, 0, tzinfo=timezone.utc)

    fifth = items[4]
    assert fifth.title == "Сьогоднішнє оновлення"
    assert fifth.url == "https://bank.gov.ua/ua/news/news/sogodni-onovlennya"
    assert fifth.summary == "Короткий опис для сьогоднішньої новини."
    assert fifth.published == datetime(2025, 10, 23, 8, 27, tzinfo=timezone.utc)

    sixth = items[5]
    assert sixth.title == "Виступ Голови Національного банку"
    assert sixth.url == "https://bank.gov.ua/ua/news/all/vistup-golovy"
    assert sixth.summary is None
    assert sixth.published == datetime(2025, 10, 23, 11, 13, tzinfo=timezone.utc)

    seventh = items[6]
    assert seventh.title == "Декларування відкрито"
    assert seventh.url == "https://bank.gov.ua/ua/news/news/deklaruvannya-vidkryto"
    assert seventh.summary == "Новий сервіс для фінансових установ уже працює."
    assert seventh.published == datetime(2024, 9, 7, 3, 0, tzinfo=timezone.utc)


def test_fetch_nbu_news_uses_client_mock():
    html = FIXTURE_PATH.read_text(encoding="utf-8")

    expected_urls = [NBU_SEARCH_URL, NBU_NEWS_URL, NBU_ALL_NEWS_URL]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) in expected_urls
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)
    async def run() -> list[NBUNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_nbu_news(client=client)

    items = asyncio.run(run())

    assert len(items) == 7


def test_fetch_nbu_news_falls_back_to_section():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    seen_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if request.url == httpx.URL(NBU_SEARCH_URL):
            return httpx.Response(200, text="<html><body></body></html>")
        if request.url == httpx.URL(NBU_NEWS_URL):
            return httpx.Response(200, text=html)
        if request.url == httpx.URL(NBU_ALL_NEWS_URL):
            return httpx.Response(500, text="")
        raise AssertionError(f"Unexpected URL {request.url}")

    transport = httpx.MockTransport(handler)

    async def run() -> list[NBUNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_nbu_news(client=client)

    items = asyncio.run(run())

    assert len(items) == 7
    assert seen_urls.count(NBU_SEARCH_URL) == 1
    assert seen_urls[0] == NBU_SEARCH_URL

def test_fetch_nbu_news_handles_error_status():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="")

    transport = httpx.MockTransport(handler)
    async def run() -> list[NBUNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_nbu_news(client=client)

    items = asyncio.run(run())

    assert items == []


def test_parse_nbu_news_json_ld_only():
    html = """
    <html>
    <head>
        <script type=\"application/ld+json\">
        {
            \"@context\": \"https://schema.org\",
            \"@type\": \"NewsArticle\",
            \"headline\": \"Окреме повідомлення\",
            \"url\": \"/ua/news/news/json-only\",
            \"datePublished\": \"2024-10-01T12:00:00+03:00\",
            \"description\": \"Сервіс працює у тестовому режимі.\"
        }
        </script>
    </head>
    <body></body>
    </html>
    """

    items = parse_nbu_news(html, now=REFERENCE_NOW)

    assert len(items) == 1
    item = items[0]
    assert item.title == "Окреме повідомлення"
    assert item.url == "https://bank.gov.ua/ua/news/news/json-only"
    assert item.summary == "Сервіс працює у тестовому режимі."
    assert item.published == datetime(2024, 10, 1, 9, 0, tzinfo=timezone.utc)
