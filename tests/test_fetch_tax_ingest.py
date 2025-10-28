import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime, timezone

import types
from unittest.mock import Mock
import sqlalchemy.ext.asyncio as sa_asyncio

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(str(Path(__file__).resolve().parents[1]))

sys.modules.setdefault("aiosqlite", types.ModuleType("aiosqlite"))

sa_asyncio.create_async_engine = Mock(return_value=Mock())

from jobs import fetch  # noqa: E402


def test_ingest_tax_article_prefers_print_body(monkeypatch):
    main_url = "https://tax.gov.ua/media-tsentr/novini/945228.html"
    print_url = "https://tax.gov.ua/media-tsentr/novini/print-945228.html"
    primary_html = "<html><body><img src=\"/images/main.jpg\" /></body></html>"
    print_html = (
        "<html><body><article><p>Основний текст з друкованої версії.</p></article></body></html>"
    )

    fetch_calls: list[str] = []
    captured: dict[str, object] = {}

    async def fake_staged_fetch_html(url: str) -> str | None:
        fetch_calls.append(url)
        if "print-" in url:
            return print_html
        return primary_html

    class DummyResult:
        def scalar_one_or_none(self):
            return None

    class DummySession:
        def __init__(self) -> None:
            self.added: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            captured["duplicate_query"] = stmt
            return DummyResult()

        def add(self, obj):
            self.added.append(obj)
            captured["article"] = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            obj.id = 1
            return None

    def fake_extract_image(html: str, base_url: str | None = None):
        captured["image_html"] = html
        captured["image_base"] = base_url
        return "https://tax.gov.ua/media/main.jpg"

    def fake_choose_summary(title: str, provided, html_text):
        captured["provided_summary"] = provided
        captured["summary_html"] = html_text
        return "Основний текст з друкованої версії."

    monkeypatch.setattr(fetch, "staged_fetch_html", fake_staged_fetch_html)
    monkeypatch.setattr(fetch, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(fetch, "extract_image", fake_extract_image)
    monkeypatch.setattr(fetch, "choose_summary", fake_choose_summary)

    status = asyncio.run(
        fetch.ingest_one(
            url=main_url,
            title="Новина",
            published=datetime.now(timezone.utc),
            summary="Сніпет зі списку",
        )
    )

    assert status == "created"
    assert fetch_calls == [main_url, print_url]
    assert captured["image_html"] == primary_html
    assert captured["image_base"] == main_url
    assert captured["summary_html"] == print_html
    assert captured["provided_summary"] is None

    article = captured["article"]
    assert article.url == main_url
    assert article.summary == "Основний текст з друкованої версії."
    assert article.image_url == "https://tax.gov.ua/media/main.jpg"


def test_ingest_tax_article_normalizes_print_url(monkeypatch):
    main_url = "https://tax.gov.ua/media-tsentr/novini/945228.html"
    print_url = "https://tax.gov.ua/media-tsentr/novini/print-945228.html"
    primary_html = "<html><body><img src=\"/images/main.jpg\" /></body></html>"
    print_html = (
        "<html><body><article><p>Основний текст з друкованої версії.</p></article></body></html>"
    )

    fetch_calls: list[str] = []
    captured: dict[str, object] = {}

    async def fake_staged_fetch_html(url: str) -> str | None:
        fetch_calls.append(url)
        if "print-" in url:
            return print_html
        return primary_html

    class DummyResult:
        def scalar_one_or_none(self):
            return None

    class DummySession:
        def __init__(self) -> None:
            self.added: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return DummyResult()

        def add(self, obj):
            self.added.append(obj)
            captured["article"] = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            obj.id = 1
            return None

    def fake_extract_image(html: str, base_url: str | None = None):
        captured["image_html"] = html
        captured["image_base"] = base_url
        return "https://tax.gov.ua/media/main.jpg"

    def fake_choose_summary(title: str, provided, html_text):
        captured["summary_html"] = html_text
        return "Основний текст з друкованої версії."

    monkeypatch.setattr(fetch, "staged_fetch_html", fake_staged_fetch_html)
    monkeypatch.setattr(fetch, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(fetch, "extract_image", fake_extract_image)
    monkeypatch.setattr(fetch, "choose_summary", fake_choose_summary)

    status = asyncio.run(
        fetch.ingest_one(
            url=print_url,
            title="Новина",
            published=datetime.now(timezone.utc),
            summary="Сніпет зі списку",
        )
    )

    assert status == "created"
    assert fetch_calls == [main_url, print_url]
    assert captured["image_html"] == primary_html
    assert captured["image_base"] == main_url
    assert captured["summary_html"] == print_html

    article = captured["article"]
    assert article.url == main_url
    assert article.image_url == "https://tax.gov.ua/media/main.jpg"


def test_ingest_tax_article_prefers_non_preview_image(monkeypatch):
    main_url = "https://tax.gov.ua/media-tsentr/novini/947477.html"
    print_url = "https://tax.gov.ua/media-tsentr/novini/print-947477.html"
    primary_html = (
        "<html><body><div class=\"article__content\">"
        "<img src=\"/data/material/000/813/947477/preview1.jpg\" />"
        "<img src=\"/data/material/000/813/947477/6900d1880b6df.jpg\" />"
        "</div></body></html>"
    )
    print_html = (
        "<html><body><article><p>Основний текст з друкованої версії.</p></article></body></html>"
    )

    fetch_calls: list[str] = []
    captured: dict[str, object] = {}

    async def fake_staged_fetch_html(url: str) -> str | None:
        fetch_calls.append(url)
        if "print-" in url:
            return print_html
        return primary_html

    class DummyResult:
        def scalar_one_or_none(self):
            return None

    class DummySession:
        def __init__(self) -> None:
            self.added: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return DummyResult()

        def add(self, obj):
            self.added.append(obj)
            captured["article"] = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            obj.id = 1
            return None

    def fake_choose_summary(title: str, provided, html_text):
        return "Основний текст з друкованої версії."

    def fake_extract_image(html: str, base_url: str | None = None):
        return "https://tax.gov.ua/data/material/000/813/947477/preview1.jpg"

    monkeypatch.setattr(fetch, "staged_fetch_html", fake_staged_fetch_html)
    monkeypatch.setattr(fetch, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(fetch, "choose_summary", fake_choose_summary)
    monkeypatch.setattr(fetch, "extract_image", fake_extract_image)

    status = asyncio.run(
        fetch.ingest_one(
            url=main_url,
            title="Новина",
            published=datetime.now(timezone.utc),
            summary="Сніпет зі списку",
        )
    )

    assert status == "created"
    assert fetch_calls == [main_url, print_url]

    article = captured["article"]
    assert (
        article.image_url
        == "https://tax.gov.ua/data/material/000/813/947477/6900d1880b6df.jpg"
    )


def test_ingest_tax_article_refetches_primary_for_image(monkeypatch):
    main_url = "https://tax.gov.ua/media-tsentr/novini/947500.html"
    print_url = "https://tax.gov.ua/media-tsentr/novini/print-947500.html"
    primary_html = "<html><body><img src=\"/data/material/000/813/947500/full.jpg\" /></body></html>"
    print_html = (
        "<html><body><article><p>Текст друкованої версії.</p></article></body></html>"
    )

    fetch_calls: list[str] = []
    captured: dict[str, object] = {}

    call_state = {"attempt": 0}

    async def fake_staged_fetch_html(url: str) -> str | None:
        fetch_calls.append(url)
        if "print-" in url:
            return print_html
        call_state["attempt"] += 1
        if call_state["attempt"] == 1:
            return None
        return primary_html

    class DummyResult:
        def scalar_one_or_none(self):
            return None

    class DummySession:
        def __init__(self) -> None:
            self.added: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return DummyResult()

        def add(self, obj):
            self.added.append(obj)
            captured["article"] = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            obj.id = 1
            return None

    def fake_extract_image(html: str, base_url: str | None = None):
        captured["image_html"] = html
        captured["image_base"] = base_url
        return "https://tax.gov.ua/media/full.jpg"

    def fake_choose_summary(title: str, provided, html_text):
        captured["summary_html"] = html_text
        return "Текст друкованої версії."

    monkeypatch.setattr(fetch, "staged_fetch_html", fake_staged_fetch_html)
    monkeypatch.setattr(fetch, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(fetch, "extract_image", fake_extract_image)
    monkeypatch.setattr(fetch, "choose_summary", fake_choose_summary)

    status = asyncio.run(
        fetch.ingest_one(
            url=main_url,
            title="Новина",
            published=datetime.now(timezone.utc),
            summary="Сніпет",
        )
    )

    assert status == "created"
    assert fetch_calls == [main_url, print_url, main_url]
    assert captured["image_html"] == primary_html
    assert captured["image_base"] == main_url
    assert captured["summary_html"] == print_html

    article = captured["article"]
    assert article.image_url == "https://tax.gov.ua/media/full.jpg"


def test_ingest_tax_article_uses_background_image_style(monkeypatch):
    main_url = "https://tax.gov.ua/media-tsentr/novini/947477.html"
    print_url = "https://tax.gov.ua/media-tsentr/novini/print-947477.html"
    primary_html = (
        "<html><body><div class=\"article__content\">"
        "<div class=\"hero\" style=\"background-image: url('/data/material/000/813/947477/6900d1880b6df.jpg');\"></div>"
        "<img src=\"/data/material/000/813/947477/preview1.jpg\" />"
        "</div></body></html>"
    )
    print_html = (
        "<html><body><article><p>Основний текст з друкованої версії.</p></article></body></html>"
    )

    fetch_calls: list[str] = []
    captured: dict[str, object] = {}

    async def fake_staged_fetch_html(url: str) -> str | None:
        fetch_calls.append(url)
        if "print-" in url:
            return print_html
        return primary_html

    class DummyResult:
        def scalar_one_or_none(self):
            return None

    class DummySession:
        def __init__(self) -> None:
            self.added: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return DummyResult()

        def add(self, obj):
            self.added.append(obj)
            captured["article"] = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            obj.id = 1
            return None

    def fake_choose_summary(title: str, provided, html_text):
        return "Основний текст з друкованої версії."

    def fake_extract_image(html: str, base_url: str | None = None):
        return "https://tax.gov.ua/data/material/000/813/947477/preview1.jpg"

    monkeypatch.setattr(fetch, "staged_fetch_html", fake_staged_fetch_html)
    monkeypatch.setattr(fetch, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(fetch, "choose_summary", fake_choose_summary)
    monkeypatch.setattr(fetch, "extract_image", fake_extract_image)

    status = asyncio.run(
        fetch.ingest_one(
            url=main_url,
            title="Новина",
            published=datetime.now(timezone.utc),
            summary="Сніпет зі списку",
        )
    )

    assert status == "created"
    assert fetch_calls == [main_url, print_url]

    article = captured["article"]
    assert (
        article.image_url
        == "https://tax.gov.ua/data/material/000/813/947477/6900d1880b6df.jpg"
    )


def test_ingest_tax_article_uses_anchor_when_image_missing(monkeypatch):
    main_url = "https://tax.gov.ua/media-tsentr/novini/947477.html"
    print_url = "https://tax.gov.ua/media-tsentr/novini/print-947477.html"
    primary_html = (
        "<html><body><div class=\"article__content\">"
        "<img src=\"/data/material/000/813/947477/preview1.jpg\" />"
        "<a href=\"/data/material/000/813/947477/6900d1880b6df.jpg\">Фото</a>"
        "</div></body></html>"
    )
    print_html = (
        "<html><body><article><p>Основний текст з друкованої версії.</p></article></body></html>"
    )

    fetch_calls: list[str] = []
    captured: dict[str, object] = {}

    async def fake_staged_fetch_html(url: str) -> str | None:
        fetch_calls.append(url)
        if "print-" in url:
            return print_html
        return primary_html

    class DummyResult:
        def scalar_one_or_none(self):
            return None

    class DummySession:
        def __init__(self) -> None:
            self.added: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return DummyResult()

        def add(self, obj):
            self.added.append(obj)
            captured["article"] = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            obj.id = 1
            return None

    def fake_choose_summary(title: str, provided, html_text):
        return "Основний текст з друкованої версії."

    def fake_extract_image(html: str, base_url: str | None = None):
        return "https://tax.gov.ua/data/material/000/813/947477/preview1.jpg"

    monkeypatch.setattr(fetch, "staged_fetch_html", fake_staged_fetch_html)
    monkeypatch.setattr(fetch, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(fetch, "choose_summary", fake_choose_summary)
    monkeypatch.setattr(fetch, "extract_image", fake_extract_image)

    status = asyncio.run(
        fetch.ingest_one(
            url=main_url,
            title="Новина",
            published=datetime.now(timezone.utc),
            summary="Сніпет зі списку",
        )
    )

    assert status == "created"
    assert fetch_calls == [main_url, print_url]

    article = captured["article"]
    assert (
        article.image_url
        == "https://tax.gov.ua/data/material/000/813/947477/6900d1880b6df.jpg"
    )

