from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

from selectolax.parser import HTMLParser

__all__ = ["tax_print_url", "discover_tax_print_url"]


_TAX_NEWS_PATH_PREFIX = "/media-tsentr/novini/"
_TAX_ID_RE = re.compile(r"(?P<id>\d{4,})")


def tax_print_url(url: str) -> Optional[str]:
    """Return the print-friendly version of a DPS news article URL."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    netloc = (parsed.netloc or "").lower()
    if "tax.gov.ua" not in netloc:
        return None

    path = parsed.path or ""
    if not path.startswith(_TAX_NEWS_PATH_PREFIX):
        return None

    if "print-" in path:
        normalized_path = path.rstrip("/")
        if not normalized_path.endswith(".html"):
            normalized_path = f"{normalized_path}.html"
        return urlunparse(parsed._replace(path=normalized_path, query="", fragment=""))

    slug = path.rstrip("/").rsplit("/", 1)[-1]
    match = _TAX_ID_RE.search(slug)
    if not match:
        return None

    article_id = match.group("id")
    print_path = f"{_TAX_NEWS_PATH_PREFIX}print-{article_id}.html"
    return urlunparse(parsed._replace(path=print_path, query="", fragment=""))


def discover_tax_print_url(url: str, html: str | None = None) -> Optional[str]:
    """Try to locate a DPS print URL using the article HTML fallback."""

    derived = tax_print_url(url)
    if not html:
        return derived

    try:
        tree = HTMLParser(html)
    except Exception:
        return derived

    selectors = (
        'link[rel*="alternate"][href*="print-"]',
        'link[media*="print"][href*="print-"]',
        'a[href*="/media-tsentr/novini/print-"]',
        'a[href*="print-"][class*="print"]',
    )

    for selector in selectors:
        node = tree.css_first(selector)
        if not node:
            continue
        href = (node.attributes.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(url, href)
        normalized = tax_print_url(absolute)
        if normalized:
            return normalized
        if "/media-tsentr/novini/" in absolute and "print-" in absolute:
            return absolute

    for node in tree.css('a[href*="print-"]'):
        href = (node.attributes.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(url, href)
        normalized = tax_print_url(absolute)
        if normalized:
            return normalized
        if "/media-tsentr/novini/" in absolute and "print-" in absolute:
            return absolute

    return derived
