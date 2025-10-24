from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, List, Sequence
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from selectolax.parser import HTMLParser, Node

log = logging.getLogger("bot")

NBU_NEWS_URL = "https://bank.gov.ua/ua/news"
NBU_ALL_NEWS_URL = "https://bank.gov.ua/ua/news/all"
NBU_SEARCH_URL = "https://bank.gov.ua/ua/news/search"
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


_MONTH_VARIANTS: dict[int, tuple[str, ...]] = {
    1: ("січня", "січ", "січ."),
    2: ("лютого", "лют", "лют."),
    3: ("березня", "берез", "бер", "бер."),
    4: ("квітня", "квіт", "квіт."),
    5: ("травня", "трав", "трав."),
    6: ("червня", "черв", "черв."),
    7: ("липня", "лип", "лип."),
    8: ("серпня", "серп", "серп."),
    9: ("вересня", "верес", "вер", "вер."),
    10: ("жовтня", "жовт", "жов", "жовт."),
    11: ("листопада", "листоп", "лист", "лист."),
    12: ("грудня", "груд", "груд."),
}

_MONTHS: dict[str, int] = {}
for month, variants in _MONTH_VARIANTS.items():
    for variant in variants:
        normalized_variant = variant.replace(".", "").lower()
        _MONTHS[normalized_variant] = month


def _parse_ukrainian_date(value: str, reference: datetime | None = None) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None

    text = raw.lower()
    text = text.replace("сьогодні", "")
    text = re.sub(r"\s+р(\.|оку)?$", "", text)
    text = text.replace(" о ", " ")
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()

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

    time_only = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*год\.?)?", text)
    if time_only:
        hour = int(time_only.group(1))
        minute = int(time_only.group(2))
        base = reference
        if base is None:
            base = datetime.now(KYIV_TZ)
        elif base.tzinfo is None:
            base = base.replace(tzinfo=KYIV_TZ)
        else:
            base = base.astimezone(KYIV_TZ)
        try:
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None

    words = re.search(r"(\d{1,2})\s+([а-яіїєґ.]+)\s+(\d{4})", text)
    if words:
        day = int(words.group(1))
        month_name = words.group(2)
        normalized_month = month_name.replace(".", "").strip()
        year = int(words.group(3))
        month = _MONTHS.get(month_name) or _MONTHS.get(normalized_month)
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
    ordered: dict[int, tuple[int, Node]] = {}

    for index, link in enumerate(root.css("a[href]")):
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
    def _scan(target: Node) -> datetime | None:
        attributes = target.attributes or {}
        raw_attr = None
        for attr in ("data-date", "data-published", "datetime"):
            raw_attr = attributes.get(attr)
            if raw_attr:
                parsed_attr = _parse_ukrainian_date(raw_attr, reference=reference)
                if parsed_attr:
                    return parsed_attr.astimezone(timezone.utc)

        class_string = (attributes.get("class") or "").lower()
        if "date" in class_string:
            text_value = target.text().strip()
            if text_value:
                parsed = _parse_ukrainian_date(text_value, reference=reference)
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
            parsed = _parse_ukrainian_date(text_value, reference=reference)
            if parsed:
                return parsed.astimezone(timezone.utc)

        for candidate in target.css('[class*="date"], [class*="time"], time'):
            text_value = candidate.text().strip()
            if not text_value:
                continue
            parsed = _parse_ukrainian_date(text_value, reference=reference)
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
        if not text or text == title:
            continue
        if title and title in text:
            remainder = text.replace(title, "", 1).strip(" -,:\n\t")
            if not remainder:
                continue
            if _parse_ukrainian_date(remainder) is not None:
                continue
        if _parse_ukrainian_date(text) is not None:
            continue
        return text

    for candidate in node.css("p, div, span"):
        class_string = (candidate.attributes.get("class") or "").lower()
        if "date" in class_string:
            continue
        text = candidate.text().strip()
        if not text or text == title:
            continue
        if title and title in text:
            remainder = text.replace(title, "", 1).strip(" -,:\n\t")
            if not remainder:
                continue
            if _parse_ukrainian_date(remainder) is not None:
                continue
        if _parse_ukrainian_date(text) is not None:
            continue
        return text

    return None


def _json_ld_nodes(tree: HTMLParser) -> Iterator[dict[str, Any]]:
    root = tree.root
    if root is None:
        return

    for script in root.css('script[type="application/ld+json"]'):
        payload = script.text().strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue

        stack: list[Any] = [data]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                yield current
                for value in current.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(current, list):
                for item in current:
                    if isinstance(item, (dict, list)):
                        stack.append(item)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = _parse_ukrainian_date(value)
        if dt is None:
            normalized = value.strip()
            if normalized:
                normalized = normalized.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(normalized)
                except ValueError:
                    dt = None
        else:
            dt = dt
    else:
        dt = None

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KYIV_TZ)
    return dt.astimezone(timezone.utc)


def parse_nbu_news(html: str, now: datetime | None = None) -> List[NBUNewsItem]:
    if now is None:
        reference_now = datetime.now(KYIV_TZ)
    elif now.tzinfo is None:
        reference_now = now.replace(tzinfo=KYIV_TZ)
    else:
        reference_now = now.astimezone(KYIV_TZ)

    tree = HTMLParser(html)
    items: list[NBUNewsItem] = []
    seen: set[str] = set()

    def add_item(url: str, title: str, published: datetime | None, summary: str | None = None) -> None:
        if not url or not title or not published:
            return
        absolute = urljoin(BASE_URL, url)
        parsed = urlparse(absolute)
        if parsed.netloc and "bank.gov.ua" not in parsed.netloc:
            return
        normalized = absolute
        if normalized in seen:
            return
        items.append(
            NBUNewsItem(
                title=title,
                url=normalized,
                published=published.astimezone(timezone.utc),
                summary=summary,
            )
        )
        seen.add(normalized)

    title_selectors: Sequence[str] = (
        ".news-list__item-title",
        ".news-card__title",
        ".news-item__title",
        ".news__title",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    )

    for node in _candidate_nodes(tree):
        link = node.css_first("a[href]")
        if link is None:
            continue
        href = (link.attributes.get("href") or "").strip()
        if not href:
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

        published = _node_date(node, reference=reference_now)
        if not published:
            continue

        summary = _node_summary(node, title)
        add_item(href, title, published, summary)

    # Fallback: JSON-LD descriptions used by modern frontends
    for payload in _json_ld_nodes(tree):
        type_field = str(payload.get("@type", "")).lower()
        if not type_field:
            continue
        if type_field in {"listitem", "listitem[]"}:
            continue

        if any(token in type_field for token in ("newsarticle", "article", "blogposting")):
            url_value = payload.get("url") or payload.get("mainEntityOfPage")
            if isinstance(url_value, dict):
                url_value = url_value.get("@id") or url_value.get("url")
            if isinstance(url_value, list) and url_value:
                url_value = url_value[0]
            if not isinstance(url_value, str):
                continue

            title_value = payload.get("headline") or payload.get("name")
            if isinstance(title_value, list):
                title_value = " ".join(str(part).strip() for part in title_value if part)
            if not isinstance(title_value, str):
                continue
            title_value = title_value.strip()
            if not title_value:
                continue

            published_value = (
                payload.get("datePublished")
                or payload.get("dateCreated")
                or payload.get("dateModified")
            )
            published_dt = _coerce_datetime(published_value)
            if not published_dt:
                continue

            summary_value = payload.get("description") or payload.get("abstract")
            if isinstance(summary_value, dict):
                summary_value = summary_value.get("@value")
            if isinstance(summary_value, list):
                summary_value = " ".join(str(part).strip() for part in summary_value if part)
            if isinstance(summary_value, str):
                summary_value = summary_value.strip()
            else:
                summary_value = None

            add_item(url_value, title_value, published_dt, summary_value)

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
        reference_now = datetime.now(KYIV_TZ)
        aggregated: list[NBUNewsItem] = []
        seen_urls: set[str] = set()
        for url in (NBU_SEARCH_URL, NBU_NEWS_URL, NBU_ALL_NEWS_URL):
            try:
                response = await client.get(url, headers=REQUEST_HEADERS)
            except httpx.HTTPError as exc:
                log.warning("NBU news fetch error url=%s error=%s", url, exc)
                continue

            if response.status_code != httpx.codes.OK or not response.text:
                log.warning(
                    "failed to load NBU news page url=%s status=%s",
                    url,
                    response.status_code,
                )
                continue

            parsed = parse_nbu_news(response.text, now=reference_now)
            if not parsed:
                log.debug("NBU news page produced no items url=%s", url)
                continue

            for item in parsed:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                aggregated.append(item)

        return aggregated
    finally:
        if close_client:
            await client.aclose()


__all__ = [
    "fetch_nbu_news",
    "parse_nbu_news",
    "NBUNewsItem",
    "NBU_NEWS_URL",
    "NBU_ALL_NEWS_URL",
    "NBU_SEARCH_URL",
]

