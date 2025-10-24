from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import asyncio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from jobs.tax_scraper import (
    TAX_NEWS_URL,
    TaxNewsItem,
    fetch_tax_news,
    parse_tax_news,
)
from services.ukrainian_dates import KYIV_TZ


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tax_news.html"
REFERENCE_NOW = datetime(2024, 11, 5, 12, 0, tzinfo=KYIV_TZ)


def test_parse_tax_news_returns_items():
    html = FIXTURE_PATH.read_text(encoding="utf-8")

    items = parse_tax_news(html, now=REFERENCE_NOW)

    assert len(items) == 4
    assert all(isinstance(item, TaxNewsItem) for item in items)

    by_url = {item.url: item for item in items}

    first = by_url["https://tax.gov.ua/media-tsentr/novini/novij-servis/"]
    assert first.title == "Новий сервіс запущено"
    assert first.summary.startswith("Державна податкова служба")
    assert first.published.astimezone(KYIV_TZ) == datetime(2024, 11, 5, 10, 15, tzinfo=KYIV_TZ)

    second = by_url["https://tax.gov.ua/media-tsentr/novini/inshi-novini/"]
    assert second.title == "Інші новини"
    assert second.summary == "Стислий опис поточного стану реформ."
    assert second.published.astimezone(KYIV_TZ) == datetime(2024, 10, 28, 14, 45, tzinfo=KYIV_TZ)

    third = by_url["https://tax.gov.ua/media-tsentr/novini/starij-material/"]
    assert third.title == "Старий матеріал"
    assert third.summary == "Короткий зміст старішої новини."
    assert third.published.astimezone(KYIV_TZ) == datetime(2024, 9, 12, 0, 0, tzinfo=KYIV_TZ)

    ld = by_url["https://tax.gov.ua/media-tsentr/novini/analityka-podatky/"]
    assert ld.title == "Аналітика щодо податкових змін"
    assert ld.summary.startswith("Роз'яснено ключові")
    assert ld.published == datetime(2024, 10, 5, 6, 30, tzinfo=timezone.utc)


def test_fetch_tax_news_uses_client_mock():
    html = FIXTURE_PATH.read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TAX_NEWS_URL
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)

    async def run() -> list[TaxNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_tax_news(client=client)

    items = asyncio.run(run())

    assert len(items) == 4


def test_fetch_tax_news_handles_error_status():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="")

    transport = httpx.MockTransport(handler)

    async def run() -> list[TaxNewsItem]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_tax_news(client=client)

    items = asyncio.run(run())

    assert items == []
