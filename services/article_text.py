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

_CONTENT_SELECTORS: Sequence[str] = (
    "p",
    "li",
    "h2",
    "h3",
    "h4",
    "blockquote",
)

_STOP_PHRASES: Sequence[str] = (
    "новини по темі",
    "по темі",
    "related",
    "Читайте також",
    "читайте також",
)


def _iter_blocks(node: Node) -> Iterable[str]:
    seen: set[str] = set()
    headline = node.css_first("h1")
    encountered_headline = headline is None
    headline_id = headline.mem_id if headline is not None else None

    for element in node.traverse():
        if headline_id is not None and element.mem_id == headline_id:
            encountered_headline = True
            continue
        if not encountered_headline:
            continue

        if element.tag not in _CONTENT_SELECTORS:
            continue

        if element.tag in {"h2", "h3", "h4"}:
            heading_text = (element.text(separator=" ") or "").strip().lower()
            if any(phrase in heading_text for phrase in _STOP_PHRASES):
                return

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


def _join_blocks(blocks: Sequence[str]) -> str | None:
    if not blocks:
        return None

    combined = "\n\n".join(blocks).strip()
    if not combined:
        return None

    if len(combined) > MAX_ARTICLE_CHARS:
        truncated = combined[:MAX_ARTICLE_CHARS]
        last_break = truncated.rfind("\n\n")
        if last_break > 2000:
            combined = truncated[:last_break].strip()
        else:
            combined = truncated.rsplit(" ", 1)[0].strip()

    return combined or None


def _iter_structural_blocks(tree: HTMLParser) -> Iterable[str]:
    headline = tree.css_first("h1")
    if headline is None:
        return

    seen: set[str] = set()
    collecting = False
    headline_id = headline.mem_id
    for element in tree.root.traverse():
        if element.mem_id == headline_id:
            collecting = True
            continue
        if not collecting:
            continue

        if element.tag in {"h2", "h3", "h4"}:
            heading_text = (element.text(separator=" ") or "").strip().lower()
            if any(phrase in heading_text for phrase in _STOP_PHRASES):
                break

        if element.tag not in _CONTENT_SELECTORS:
            continue

        text = (element.text(separator=" ") or "").strip()
        if not text or len(text) < 4:
            continue
        if text in seen:
            continue
        seen.add(text)
        yield text


def _candidate_nodes(tree: HTMLParser) -> Iterable[Node]:
    seen: set[int] = set()

    for selector in _PRIMARY_SELECTORS:
        node = tree.css_first(selector)
        if node is not None and node.mem_id not in seen:
            seen.add(node.mem_id)
            yield node

    for selector in _SECONDARY_SELECTORS:
        node = tree.css_first(selector)
        if node is not None and node.mem_id not in seen:
            seen.add(node.mem_id)
            yield node

    root = tree.css_first("article")
    if root is not None and root.mem_id not in seen:
        seen.add(root.mem_id)
        yield root

    headline = tree.css_first("h1")
    if headline is not None:
        ancestor = headline.parent
        while ancestor is not None:
            if ancestor.mem_id not in seen:
                seen.add(ancestor.mem_id)
                yield ancestor
            ancestor = ancestor.parent


def extract_article_text(html: str) -> str | None:
    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    for node in _candidate_nodes(tree):
        blocks = list(_iter_blocks(node))
        combined = _join_blocks(blocks)
        if combined:
            return combined

    structural_blocks = list(_iter_structural_blocks(tree))
    return _join_blocks(structural_blocks)


__all__ = ["extract_article_text"]
