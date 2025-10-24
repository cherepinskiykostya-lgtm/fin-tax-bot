from __future__ import annotations

from typing import Iterable, Sequence

import re

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

_STOP_HEADLINE_PHRASES: Sequence[str] = (
    "новини по темі",
    "по темі",
    "related",
    "Читайте також",
    "читайте також",
)

_STOP_SECTION_PHRASES: Sequence[str] = (
    "теги",
    "поділитися",
    "поделиться",
    "останні новини",
    "останні публікації",
    "related",
    "Читайте також",
    "читайте також",
)


_STOP_HEADLINE_PHRASES_LOWER: Sequence[str] = tuple(
    phrase.lower() for phrase in _STOP_HEADLINE_PHRASES
)
_STOP_SECTION_PHRASES_LOWER: Sequence[str] = tuple(
    phrase.lower() for phrase in _STOP_SECTION_PHRASES
)

_DATE_PATTERN = re.compile(
    r"\b\d{1,2}\s+[А-Яа-яІіЄєҐґ\.]{2,}\.?\s+\d{4}\s+\d{1,2}:\d{2}\b"
    r"|\b\d{1,2}:\d{2}\b",
    flags=re.IGNORECASE,
)


def _iter_blocks(node: Node) -> Iterable[str]:
    seen: set[str] = set()
    headlines = node.css("h1")

    if not headlines:
        yield from _iter_fallback_children(node, seen)
        return

    for headline in headlines:
        blocks = _collect_after_headline(node, headline, seen)
        if blocks:
            for block in blocks:
                yield block
            return


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


def _iter_fallback_children(node: Node, seen: set[str]) -> Iterable[str]:
    child = node.child
    while child is not None:
        if child.tag in {"script", "style", "noscript"}:
            child = child.next
            continue

        text = (child.text(separator=" ") or "").strip()
        if text:
            lowered = text.lower()
            if any(phrase in lowered for phrase in _STOP_SECTION_PHRASES_LOWER):
                return
            if len(text) >= 4 and text not in seen:
                seen.add(text)
                yield text

        child = child.next


def _next_node_in_document(node: Node, boundary: Node) -> Node | None:
    if node.child is not None:
        return node.child

    current = node
    while current is not None and current is not boundary:
        if current.next is not None:
            return current.next
        current = current.parent
    return None


def _collect_after_headline(node: Node, headline: Node, seen: set[str]) -> list[str]:
    blocks: list[str] = []
    local_seen: set[str] = set()
    current: Node | None = headline
    skipped_date = False

    while True:
        current = _next_node_in_document(current, node)
        if current is None:
            break

        if current.tag is None:
            continue

        if current.tag == "h1" and current.mem_id != headline.mem_id:
            break

        if current.tag in {"script", "style", "noscript"}:
            continue

        if current.tag not in _CONTENT_SELECTORS:
            continue

        text = (current.text(separator=" ") or "").strip()
        if not text or len(text) < 4:
            continue

        lowered = text.lower()

        if current.tag in {"h2", "h3", "h4"} and any(
            phrase in lowered for phrase in _STOP_HEADLINE_PHRASES_LOWER
        ):
            break

        if any(phrase in lowered for phrase in _STOP_SECTION_PHRASES_LOWER):
            break

        if not skipped_date and _DATE_PATTERN.search(text):
            skipped_date = True
            continue

        skipped_date = True

        if text in seen or text in local_seen:
            continue

        local_seen.add(text)
        seen.add(text)
        blocks.append(text)

    return blocks


def _iter_structural_blocks(tree: HTMLParser) -> Iterable[str]:
    seen: set[str] = set()
    seen_headlines: set[int] = set()

    for headline in tree.css("h1"):
        if headline.mem_id in seen_headlines:
            continue
        seen_headlines.add(headline.mem_id)
        blocks = _collect_after_headline(tree.root, headline, seen)
        if blocks:
            for block in blocks:
                yield block
            return


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

    for headline in tree.css("h1"):
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
