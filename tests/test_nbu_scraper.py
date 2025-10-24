from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import asyncio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from jobs.nbu_scraper import (
    NBUNewsItem,
    NBU_NEWS_URL,
    fetch_nbu_news,
    parse_nbu_news,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nbu_news.html"


def test_parse_nbu_news_returns_items():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    items = parse_nbu_news(html)

    assert len(items) == 4
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


def test_fetch_nbu_news_uses_client_mock():
    html = FIXTURE_PATH.read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(NBU_NEWS_URL)
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)
    async def run() -> list[NBUNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_nbu_news(client=client)

    items = asyncio.run(run())

    assert len(items) == 4


def test_fetch_nbu_news_handles_error_status():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="")

    transport = httpx.MockTransport(handler)
    async def run() -> list[NBUNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_nbu_news(client=client)

    items = asyncio.run(run())

    assert items == []
