from __future__ import annotations

import html
from typing import Optional

_NONBREAKING_WHITESPACE = "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
_SPACE_TRANSLATION = {ord(ch): " " for ch in _NONBREAKING_WHITESPACE}
_SPACE_TRANSLATION[ord("\ufeff")] = None


def _normalize_space_chars(text: str) -> str:
    if not text:
        return text
    return text.translate(_SPACE_TRANSLATION)

from selectolax.parser import HTMLParser

from services.article_text import extract_article_text


def _normalize_paragraphs(text: str) -> str:
    text = _normalize_space_chars(text)
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush_buffer() -> None:
        if buffer:
            paragraph = " ".join(buffer).strip()
            if paragraph:
                paragraphs.append(paragraph)
            buffer.clear()

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            flush_buffer()
            continue
        buffer.append(" ".join(stripped.split()))

    flush_buffer()

    if not paragraphs:
        return ""

    return "\n\n".join(paragraphs).strip()


def normalize_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        normalized = _normalize_paragraphs(value)
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
