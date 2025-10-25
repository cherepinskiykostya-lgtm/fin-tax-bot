from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

__all__ = ["tax_print_url"]


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
