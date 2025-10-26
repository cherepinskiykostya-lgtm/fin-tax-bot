from __future__ import annotations

from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

__all__ = ["extract_image"]


def extract_image(html: str, base_url: str | None = None) -> str | None:
    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    def _normalize_candidate(value: str | None) -> str | None:
        if not value:
            return None
        candidate = value.strip()
        if not candidate:
            return None
        candidate = candidate.strip("\"'")
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

    def _pick_from_srcset(value: str | None) -> str | None:
        if not value:
            return None
        best_url: str | None = None
        best_score = -1.0
        for chunk in value.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = chunk.split()
            if not parts:
                continue
            candidate = _normalize_candidate(parts[0])
            if not candidate:
                continue
            descriptor = parts[1] if len(parts) > 1 else ""
            score = 0.0
            if descriptor.endswith("w"):
                try:
                    score = float(descriptor[:-1])
                except ValueError:
                    score = 0.0
            elif descriptor.endswith("x"):
                try:
                    score = float(descriptor[:-1]) * 1000
                except ValueError:
                    score = 0.0
            if score > best_score or best_url is None:
                best_url = candidate
                best_score = score
        return best_url

    meta_selectors = (
        'meta[property="og:image"]',
        'meta[property="og:image:url"]',
        'meta[property="og:image:secure_url"]',
        'meta[name="twitter:image"]',
        'meta[name="twitter:image:src"]',
    )
    for selector in meta_selectors:
        for el in tree.css(selector):
            normalized = _normalize_candidate(el.attributes.get("content"))
            if normalized:
                return normalized

    link = tree.css_first('link[rel="image_src"]')
    if link:
        normalized = _normalize_candidate(link.attributes.get("href"))
        if normalized:
            return normalized

    for source in tree.css("picture source[srcset], source[data-srcset], source[srcset]"):
        normalized = _pick_from_srcset(
            source.attributes.get("srcset") or source.attributes.get("data-srcset")
        )
        if normalized:
            return normalized

    img_attr_order = (
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-srcset",
        "srcset",
        "src",
    )
    for img in tree.css("img"):
        attrs = img.attributes or {}
        for attr in img_attr_order:
            if attr not in attrs:
                continue
            if attr in {"srcset", "data-srcset"}:
                normalized = _pick_from_srcset(attrs.get(attr))
            else:
                normalized = _normalize_candidate(attrs.get(attr))
            if normalized:
                return normalized

    return None
