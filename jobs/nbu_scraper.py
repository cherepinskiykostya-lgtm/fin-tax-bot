from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from selectolax.parser import HTMLParser, Node

log = logging.getLogger("bot")

NBU_NEWS_URL = "https://bank.gov.ua/ua/news/news"
BASE_URL = "https://bank.gov.ua"

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:  # pragma: no cover
    KYIV_TZ = timezone.utc

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}


@dataclass(slots=True)
class NBUNewsItem:
    title: str
    url: str
    published: datetime
    summary: str | None = None


_MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


def _parse_ukrainian_date(value: str) -> datetime | None:
    text = value.strip().lower()
    if not text:
        return None

    text = re.sub(r"\s+р(\.|оку)?$", "", text)

    iso_match = re.search(
        r"(\d{4}-\d{2}-\d{2}t\d{2}:\d{2}(?::\d{2})?(?:[+\-]\d{2}:?\d{2}|z)?)",
        text,
    )
    if iso_match:
        iso_value = iso_match.group(1).replace("z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KYIV_TZ)
            return dt
        except ValueError:
            pass

    dotted = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if dotted:
        day, month, year = dotted.groups()
        try:
            return datetime(
                int(year),
                int(month),
                int(day),
                tzinfo=KYIV_TZ,
            )
        except ValueError:
            return None

    words = re.search(r"(\d{1,2})\s+([а-яіїєґ]+)\s+(\d{4})", text)
    if words:
        day = int(words.group(1))
        month_name = words.group(2)
        year = int(words.group(3))
        month = _MONTHS.get(month_name)
        if month is None:
            return None
        hour = minute = 0
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
        try:
            return datetime(year, month, day, hour, minute, tzinfo=KYIV_TZ)
        except ValueError:
            return None
    return None


def _candidate_nodes(tree: HTMLParser) -> Iterable[Node]:
    root = tree.root
    if root is None:
        return

    allowed_tags = {"article", "div", "li", "section"}
    seen: set[int] = set()

    for link in root.css("a[href]"):
        href = (link.attributes.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        href_lower = href.lower()
        if "news" not in href_lower:
            continue
        absolute = urljoin(BASE_URL, href)
        parsed = urlparse(absolute)
        if parsed.netloc and "bank.gov.ua" not in parsed.netloc:
            continue

        container: Node | None = link
        depth = 0
        while container is not None and depth < 5:
            if container.tag in allowed_tags:
                marker = id(container)
                if marker not in seen:
                    seen.add(marker)
                    yield container
                break
            container = container.parent
            depth += 1


def _node_date(node: Node) -> datetime | None:
    def _scan(target: Node) -> datetime | None:
        attributes = target.attributes or {}
        raw_attr = None
        for attr in ("data-date", "data-published", "datetime"):
            raw_attr = attributes.get(attr)
            if raw_attr:
                parsed_attr = _parse_ukrainian_date(raw_attr)
                if parsed_attr:
                    return parsed_attr.astimezone(timezone.utc)

        class_string = (attributes.get("class") or "").lower()
        if "date" in class_string:
            text_value = target.text().strip()
            if text_value:
                parsed = _parse_ukrainian_date(text_value)
                if parsed:
                    return parsed.astimezone(timezone.utc)

        time_tag = target.css_first("time")
        if time_tag is not None:
            datetime_value = time_tag.attributes.get("datetime") if time_tag.attributes else None
            if datetime_value:
                normalized = datetime_value.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(normalized)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=KYIV_TZ)
                    return dt.astimezone(timezone.utc)
                except ValueError:
                    pass
            text_value = time_tag.text().strip()
            parsed = _parse_ukrainian_date(text_value)
            if parsed:
                return parsed.astimezone(timezone.utc)

        for candidate in target.css('[class*="date"], time'):
            text_value = candidate.text().strip()
            if not text_value:
                continue
            parsed = _parse_ukrainian_date(text_value)
            if parsed:
                return parsed.astimezone(timezone.utc)
        return None

    current: Node | None = node
    depth = 0
    while current is not None and depth < 4:
        found = _scan(current)
        if found:
            return found
        # try immediate siblings as dates can sit next to the card container
        for neighbor in (current.next, current.prev):
            steps = 0
            sibling = neighbor
            while sibling is not None and steps < 2:
                found = _scan(sibling)
                if found:
                    return found
                sibling = sibling.next if neighbor is current.next else sibling.prev
                steps += 1
        current = current.parent
        depth += 1

    return None


def _node_summary(node: Node, title: str) -> str | None:
    priority_selectors: Sequence[str] = (
        ".news-list__item-desc",
        ".news-card__text",
        ".news-item__text",
        ".news__text",
        ".news__summary",
        ".news-feed__item-text",
        ".article__summary",
    )
    for selector in priority_selectors:
        target = node.css_first(selector)
        if target is None:
            continue
        text = target.text().strip()
        if text and text != title:
            return text

    for candidate in node.css("p, div, span"):
        class_string = (candidate.attributes.get("class") or "").lower()
        if "date" in class_string:
            continue
        text = candidate.text().strip()
        if text and text != title:
            return text

    parent = node.parent
    depth = 0
    while parent is not None and depth < 3:
        for candidate in parent.css("p, div, span"):
            class_string = (candidate.attributes.get("class") or "").lower()
            if "date" in class_string:
                continue
            text = candidate.text().strip()
            if text and text != title:
                return text
        parent = parent.parent
        depth += 1
    return None


def parse_nbu_news(html: str) -> List[NBUNewsItem]:
    tree = HTMLParser(html)
    items: list[NBUNewsItem] = []
    seen: set[str] = set()

    title_selectors: Sequence[str] = (
        ".news-list__item-title",
        ".news-card__title",
        ".news-item__title",
        ".news__title",
        "h1",
        "h2",
        "h3",
        "h4",
    )

    for node in _candidate_nodes(tree):
        link = node.css_first("a[href]")
        if link is None:
            continue
        href = (link.attributes.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(BASE_URL, href)
        if url in seen:
            continue

        title = None
        for selector in title_selectors:
            title_node = node.css_first(selector)
            if title_node is None:
                continue
            candidate = title_node.text().strip()
            if candidate:
                title = candidate
                break
        if not title:
            raw = link.text().strip()
            if raw:
                parts = [segment.strip() for segment in raw.splitlines() if segment.strip()]
                if parts:
                    title = parts[0]
        if not title:
            continue

        published = _node_date(node)
        if not published:
            continue

        summary = _node_summary(node, title)
        items.append(NBUNewsItem(title=title, url=url, published=published, summary=summary))
        seen.add(url)

    return items


async def fetch_nbu_news(client: httpx.AsyncClient | None = None) -> List[NBUNewsItem]:
    close_client = False
    if client is None:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=20,
            headers=REQUEST_HEADERS,
        )
        close_client = True

    try:
        response = await client.get(NBU_NEWS_URL, headers=REQUEST_HEADERS)
        if response.status_code != httpx.codes.OK or not response.text:
            log.warning(
                "failed to load NBU news page status=%s", response.status_code
            )
            return []
        return parse_nbu_news(response.text)
    except httpx.HTTPError as exc:
        log.warning("NBU news fetch error: %s", exc)
        return []
    finally:
        if close_client:
            await client.aclose()


__all__ = ["fetch_nbu_news", "parse_nbu_news", "NBUNewsItem", "NBU_NEWS_URL"]

