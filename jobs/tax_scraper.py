from __future__ import annotations

import importlib.util
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, List
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser, Node

from services.ukrainian_dates import KYIV_TZ, parse_ukrainian_date

log = logging.getLogger("bot")

TAX_NEWS_URL = "https://www.tax.gov.ua/media-tsentr/novini/"
BASE_URL = "https://tax.gov.ua"

REQUEST_HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9," 
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

HTTP2_SUPPORTED = importlib.util.find_spec("h2") is not None


@dataclass(slots=True)
class TaxNewsItem:
    title: str
    url: str
    published: datetime
    summary: str | None = None


def _normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    href = value.strip()
    if not href:
        return None
    absolute = urljoin(BASE_URL, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and "tax.gov.ua" not in parsed.netloc:
        return None
    return absolute


def _candidate_nodes(tree: HTMLParser) -> Iterable[Node]:
    root = tree.root
    if root is None:
        return []

    allowed_tags = {"article", "div", "li", "section"}
    ordered: dict[int, tuple[int, Node]] = {}

    for index, link in enumerate(root.css("a[href]")):
        href = (link.attributes.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        href_lower = href.lower()
        if "nov" not in href_lower and "media" not in href_lower:
            continue
        absolute = _normalize_url(href)
        if not absolute:
            continue

        container: Node | None = link
        depth = 0
        while container is not None and depth < 6:
            if container.tag in allowed_tags:
                marker = container.mem_id
                if marker not in ordered:
                    ordered[marker] = (index, container)
                break
            container = container.parent
            depth += 1

    for _, node in sorted(ordered.values(), key=lambda item: item[0]):
        yield node


def _node_date(node: Node, reference: datetime | None = None) -> datetime | None:
    def _try_parse(value: str | None) -> datetime | None:
        parsed = parse_ukrainian_date(value or "", reference=reference)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KYIV_TZ)
        return parsed.astimezone(timezone.utc)

    attributes = node.attributes or {}
    for attr in ("data-date", "data-published", "datetime"):
        raw_attr = attributes.get(attr)
        parsed = _try_parse(raw_attr)
        if parsed:
            return parsed

    for selector in ("[datetime]", "[data-date]", "[data-published]", "time"):
        for el in node.css(selector):
            attrs = el.attributes or {}
            for attr in ("datetime", "data-date", "data-published"):
                parsed = _try_parse(attrs.get(attr))
                if parsed:
                    return parsed
            parsed = _try_parse((el.text() or "").strip())
            if parsed:
                return parsed

    for el in node.css(".date, .time, .news__date, .item-date, span, p, div"):
        text = (el.text() or "").strip()
        if not text:
            continue
        parsed = _try_parse(text)
        if parsed:
            return parsed

    text = (node.text() or "")
    for chunk in re.split(r"[|•\n]", text):
        chunk_text = chunk.strip()
        if not chunk_text:
            continue
        parsed = _try_parse(chunk_text)
        if parsed:
            return parsed
    return None


def _node_title(node: Node) -> str | None:
    link = node.css_first("a[href]")
    if link is not None:
        text = (link.text() or "").strip()
        if text:
            return text

    for selector in ("h1", "h2", "h3", "h4"):
        header = node.css_first(selector)
        if header is not None:
            text = (header.text() or "").strip()
            if text:
                return text
    text = (node.text() or "").strip()
    return text or None


def _node_summary(node: Node, title: str) -> str | None:
    title_lower = title.lower()
    seen: set[str] = set()
    for selector in ("p", "div", "span"):
        for el in node.css(selector):
            text = (el.text() or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered == title_lower:
                continue
            if parse_ukrainian_date(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            if len(text) >= 30 or text.endswith("."):
                return text
    return None


def _node_url(node: Node) -> str | None:
    link = node.css_first("a[href]")
    if link is None:
        return None
    return _normalize_url(link.attributes.get("href"))


def _iter_ld_articles(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _iter_ld_articles(item)
        return
    if not isinstance(data, dict):
        return

    if "@graph" in data and isinstance(data["@graph"], list):
        for item in data["@graph"]:
            yield from _iter_ld_articles(item)

    type_value = data.get("@type")
    if isinstance(type_value, list):
        types = {t.lower() for t in type_value if isinstance(t, str)}
    elif isinstance(type_value, str):
        types = {type_value.lower()}
    else:
        types = set()

    if {"newsarticle", "article"} & types:
        yield data


def _parse_json_ld(tree: HTMLParser, reference: datetime | None = None) -> List[TaxNewsItem]:
    items: list[TaxNewsItem] = []
    seen_urls: set[str] = set()

    for script in tree.css('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.text() or "{}")
        except json.JSONDecodeError:
            continue
        for node in _iter_ld_articles(payload):
            title = node.get("headline") or node.get("name")
            url = _normalize_url(node.get("url"))
            if not title or not url or url in seen_urls:
                continue
            date_value = (
                node.get("datePublished")
                or node.get("dateCreated")
                or node.get("dateModified")
            )
            published = parse_ukrainian_date(date_value or "", reference=reference)
            if not published:
                continue
            if published.tzinfo is None:
                published = published.replace(tzinfo=KYIV_TZ)
            summary = node.get("description") or node.get("abstract")
            items.append(
                TaxNewsItem(
                    title=title.strip(),
                    url=url,
                    published=published.astimezone(timezone.utc),
                    summary=(summary.strip() if isinstance(summary, str) else None),
                )
            )
            seen_urls.add(url)
    return items


def parse_tax_news(html: str, now: datetime | None = None) -> List[TaxNewsItem]:
    try:
        tree = HTMLParser(html)
    except Exception:
        return []

    reference_now = now
    if reference_now is not None and reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=KYIV_TZ)

    items: list[TaxNewsItem] = []
    seen_urls: set[str] = set()

    for item in _parse_json_ld(tree, reference=reference_now):
        seen_urls.add(item.url)
        items.append(item)

    for node in _candidate_nodes(tree):
        url = _node_url(node)
        if not url or url in seen_urls:
            continue
        title = _node_title(node)
        if not title:
            continue
        published = _node_date(node, reference=reference_now)
        if not published:
            continue
        summary = _node_summary(node, title)
        items.append(TaxNewsItem(title=title, url=url, published=published, summary=summary))
        seen_urls.add(url)

    return items


async def fetch_tax_news(client: httpx.AsyncClient | None = None) -> List[TaxNewsItem]:
    close_client = False
    referer_headers = {**REQUEST_HEADERS_BROWSER, "Referer": "https://www.tax.gov.ua/"}

    if client is None:
        client = httpx.AsyncClient(
            headers=REQUEST_HEADERS_BROWSER,
            timeout=30,
            follow_redirects=True,
            http2=HTTP2_SUPPORTED,
        )
        close_client = True

    try:
        try:
            warmup = await client.get("https://www.tax.gov.ua/", headers=REQUEST_HEADERS_BROWSER)
            if warmup.status_code not in (200, 204):
                log.debug("tax.gov.ua warmup status=%s", warmup.status_code)
        except Exception as warmup_exc:
            log.debug("tax.gov.ua warmup error: %s", warmup_exc)

        response = await client.get(TAX_NEWS_URL, headers=referer_headers)
        html_text: str | None = None
        if response.status_code == 403:
            alt_urls = [
                TAX_NEWS_URL.rstrip("/"),
                "https://www.tax.gov.ua/media-tsentr/novini",
                "https://www.tax.gov.ua/media-tsentr/",
            ]
            for alt in alt_urls:
                alt_response = await client.get(alt, headers=referer_headers)
                if alt_response.status_code == 200 and alt_response.text:
                    html_text = alt_response.text
                    break
            if html_text is None:
                log.warning("tax news fetch status 403 after retries")
                return []
        elif response.status_code == 200 and response.text:
            html_text = response.text
        else:
            log.warning("tax news fetch status %s", response.status_code)
            return []

        if not html_text:
            log.warning("tax news fetch returned empty body")
            return []

        reference_now = datetime.now(KYIV_TZ)
        return parse_tax_news(html_text, now=reference_now)
    except Exception:
        log.exception("tax news fetch error")
        return []
    finally:
        if close_client:
            await client.aclose()


__all__ = ["TaxNewsItem", "fetch_tax_news", "parse_tax_news", "TAX_NEWS_URL"]
