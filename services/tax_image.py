"""Helpers for DPS (tax.gov.ua) article images."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

__all__ = ["prefer_tax_article_image"]


def _normalize_candidate(value: str | None, base_url: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().strip("\"'")
    if not candidate or candidate.startswith("data:"):
        return None
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif base_url:
        candidate = urljoin(base_url, candidate)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    return candidate


def _pick_from_srcset(value: str | None, base_url: str | None) -> str | None:
    if not value:
        return None
    best: str | None = None
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        candidate = chunk.split()[0]
        normalized = _normalize_candidate(candidate, base_url)
        if normalized and "preview" not in normalized.lower():
            return normalized
        if best is None and normalized:
            best = normalized
    return best


def prefer_tax_article_image(
    html: str,
    *,
    base_url: str | None,
    fallback: str | None,
) -> str | None:
    """Prefer a non-preview image for DPS articles.

    The print version of a DPS article serves a low-resolution preview image
    (``preview*.jpg``). This helper scans the canonical article HTML to find a
    better candidate. If no high-resolution image is located, the ``fallback``
    value is returned.
    """

    if fallback and "preview" not in fallback.lower():
        return fallback

    try:
        tree = HTMLParser(html)
    except Exception:
        return fallback

    def _good(candidate: str | None) -> str | None:
        if not candidate:
            return None
        if "preview" in candidate.lower():
            return None
        return candidate

    # Look through <source> elements first to capture <picture> sources.
    for source in tree.css("picture source[srcset], source[data-srcset], source[srcset]"):
        attrs = source.attributes or {}
        normalized = _pick_from_srcset(
            attrs.get("srcset") or attrs.get("data-srcset"),
            base_url,
        )
        candidate = _good(normalized)
        if candidate:
            return candidate

    attr_order = (
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-srcset",
        "srcset",
        "src",
    )

    selectors = (
        ".article__content img",
        ".news__content img",
        "article img",
        "img",
    )

    for selector in selectors:
        for img in tree.css(selector):
            attrs = img.attributes or {}
            for attr in attr_order:
                if attr not in attrs:
                    continue
                if attr in {"srcset", "data-srcset"}:
                    normalized = _pick_from_srcset(attrs.get(attr), base_url)
                else:
                    normalized = _normalize_candidate(attrs.get(attr), base_url)
                candidate = _good(normalized)
                if candidate:
                    return candidate

    return fallback

