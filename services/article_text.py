from __future__ import annotations

from typing import Iterable, Sequence

from selectolax.parser import HTMLParser, Node

MAX_ARTICLE_CHARS = 4000

_PRIMARY_SELECTORS: Sequence[str] = (
    ".article__content",
    ".article__body",
    ".article__text",
    ".news__content",
    ".news__text",
    "main article",
    "article",
)

_SECONDARY_SELECTORS: Sequence[str] = (
    "main",
    "section",
    "div[data-component='article']",
    "div[itemprop='articleBody']",
)


def _iter_blocks(node: Node) -> Iterable[str]:
    seen: set[str] = set()
    for selector in ("p", "li"):
        for element in node.css(selector):
            text = (element.text(separator=" ") or "").strip()
            if not text:
                continue
            if len(text) < 4:
                continue
            if text in seen:
                continue
            seen.add(text)
            yield text

    if not seen:
        fallback = (node.text(separator=" ") or "").strip()
        if fallback and fallback not in seen:
            yield fallback


def _candidate_nodes(tree: HTMLParser) -> Iterable[Node]:
    for selector in _PRIMARY_SELECTORS:
        node = tree.css_first(selector)
        if node is not None:
            yield node

    for selector in _SECONDARY_SELECTORS:
        node = tree.css_first(selector)
        if node is not None:
            yield node

    root = tree.css_first("article")
    if root is not None:
        yield root


def extract_article_text(html: str) -> str | None:
    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    for node in _candidate_nodes(tree):
        blocks = list(_iter_blocks(node))
        if not blocks:
            continue
        combined = "\n\n".join(blocks).strip()
        if not combined:
            continue
        if len(combined) > MAX_ARTICLE_CHARS:
            truncated = combined[:MAX_ARTICLE_CHARS]
            last_break = truncated.rfind("\n\n")
            if last_break > 2000:
                combined = truncated[:last_break].strip()
            else:
                combined = truncated.rsplit(" ", 1)[0].strip()
        if combined:
            return combined

    return None


__all__ = ["extract_article_text"]
