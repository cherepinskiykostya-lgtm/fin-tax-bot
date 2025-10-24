from __future__ import annotations

import html
from typing import Optional

from selectolax.parser import HTMLParser

from services.article_text import extract_article_text


def normalize_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        lines = [" ".join(segment.split()).strip() for segment in value.splitlines()]
        normalized = "\n".join(filter(None, lines)).strip()
    else:
        normalized = " ".join(str(value).split()).strip()
    return normalized or None


def meta_description(html_text: str) -> Optional[str]:
    try:
        tree = HTMLParser(html_text)
    except Exception:
        return None

    selectors = (
        'meta[property="og:description"]',
        'meta[name="description"]',
        'meta[name="twitter:description"]',
    )
    for selector in selectors:
        node = tree.css_first(selector)
        if not node:
            continue
        content = node.attributes.get("content") or ""
        content = html.unescape(content).strip()
        normalized = normalize_text(content)
        if normalized:
            return normalized
    return None


def choose_summary(title: str, provided: Optional[str], html_text: Optional[str]) -> Optional[str]:
    title_norm = normalize_text(title)
    summary_norm = normalize_text(provided)
    if summary_norm and title_norm and summary_norm.casefold() == title_norm.casefold():
        summary_norm = None

    if summary_norm:
        return summary_norm

    if not html_text:
        return summary_norm

    fallback = meta_description(html_text)
    if fallback and (not title_norm or fallback.casefold() != title_norm.casefold()):
        return fallback

    article_text = extract_article_text(html_text)
    if article_text:
        return article_text

    return summary_norm
