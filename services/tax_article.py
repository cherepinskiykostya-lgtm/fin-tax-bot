from __future__ import annotations

import logging
import re
from typing import Iterable, Sequence

from selectolax.parser import HTMLParser, Node

log = logging.getLogger(__name__)

MAX_ARTICLE_LENGTH = 5000

_PRIMARY_SELECTORS: Sequence[str] = (
    ".article__content",
    ".article__body",
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

_CONTENT_TAGS = {
    "p",
    "ul",
    "ol",
    "li",
    "blockquote",
    "table",
    "tr",
    "td",
    "h2",
    "h3",
}

_STOP_PHRASES: Sequence[str] = (
    "теги",
    "поділитися",
    "поделиться",
    "останні новини",
    "останні публікації",
    "related",
    "Читайте також",
    "читайте також",
)

_DATE_RE = re.compile(
    r"\b\d{1,2}\s+[А-Яа-яІіЄєҐґ\.]{2,}\.?\s+\d{4}\b"
    r"|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b"
    r"|\b\d{1,2}:\d{2}\b",
    flags=re.IGNORECASE,
)

_MIN_DIRECT_DIV_LENGTH = 80


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip()


def _direct_text(node: Node) -> str:
    parts: list[str] = []
    child = node.child
    while child is not None:
        tag = child.tag
        if tag is None or tag == "-text":
            chunk = (child.text() or "").strip()
            if chunk:
                parts.append(chunk)
        child = child.next
    if not parts:
        return ""
    return _normalize(" ".join(parts))


def _has_whitelisted_descendant(node: Node) -> bool:
    for descendant in node.iter():
        if descendant is node:
            continue
        tag = (descendant.tag or "").lower()
        if tag in _CONTENT_TAGS:
            return True
    return False


def _is_atomic_div(node: Node) -> bool:
    return not _has_whitelisted_descendant(node)


def _is_stop_text(text: str) -> bool:
    lowered = text.casefold()
    return any(phrase in lowered for phrase in _STOP_PHRASES)


def _is_date_like(text: str) -> bool:
    return bool(_DATE_RE.search(text))


def _should_include(text: str, title: str | None, seen: set[str]) -> bool:
    if not text:
        return False
    if text in seen:
        return False
    if title and text.casefold() == title.casefold():
        return False
    if _is_stop_text(text):
        return False
    return True


def _collect_blocks(
    node: Node,
    *,
    title: str | None,
    seen: set[str],
    stats: dict[str, int],
) -> list[str]:
    blocks: list[str] = []

    child = node.child
    while child is not None:
        tag = (child.tag or "").lower() if child.tag else None
        if tag is None:
            child = child.next
            continue

        if tag in {"script", "style", "noscript"}:
            child = child.next
            continue

        if tag == "div":
            if _is_atomic_div(child):
                text = _normalize(child.text(separator=" ") or "")
                if (
                    text
                    and len(text) >= 40
                    and not _is_date_like(text)
                    and _should_include(text, title, seen)
                ):
                    seen.add(text)
                    blocks.append(text)
                    stats["atomic_divs"] += 1
                child = child.next
                continue

            stats["non_atomic_divs"] += 1
            direct = _direct_text(child)
            if (
                direct
                and len(direct) >= _MIN_DIRECT_DIV_LENGTH
                and not _is_date_like(direct)
                and _should_include(direct, title, seen)
            ):
                seen.add(direct)
                blocks.append(direct)
                stats["direct_divs"] += 1

            blocks.extend(_collect_blocks(child, title=title, seen=seen, stats=stats))
            child = child.next
            continue

        if tag in {"ul", "ol"}:
            items: list[str] = []
            for li in child.css("li"):
                text = _normalize(li.text(separator=" ") or "")
                if not text or _is_date_like(text):
                    continue
                bullet = f"• {text}"
                if _should_include(bullet, title, seen):
                    seen.add(bullet)
                    items.append(bullet)
            if items:
                blocks.extend(items)
            child = child.next
            continue

        if tag == "li":
            text = _normalize(child.text(separator=" ") or "")
            if text and not _is_date_like(text):
                bullet = f"• {text}"
                if _should_include(bullet, title, seen):
                    seen.add(bullet)
                    blocks.append(bullet)
            child = child.next
            continue

        if tag in _CONTENT_TAGS:
            text = _normalize(child.text(separator=" ") or "")
            if text and not _is_date_like(text) and _should_include(text, title, seen):
                seen.add(text)
                blocks.append(text)
            child = child.next
            continue

        blocks.extend(_collect_blocks(child, title=title, seen=seen, stats=stats))
        child = child.next

    return blocks


def _score_container(node: Node) -> int:
    score = 0
    for el in node.traverse():
        tag = (el.tag or "").lower() if el.tag else None
        if tag is None or tag in {"script", "style", "noscript"}:
            continue
        if tag == "div":
            direct = _direct_text(el)
            if len(direct) >= _MIN_DIRECT_DIV_LENGTH:
                score += len(direct)
            else:
                text = _normalize(el.text(separator=" ") or "")
                if len(text) >= 40:
                    score += len(text)
            continue
        if tag in _CONTENT_TAGS:
            text = _normalize(el.text(separator=" ") or "")
            score += len(text)
    return score


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

    article = tree.css_first("article")
    if article is not None and article.mem_id not in seen:
        seen.add(article.mem_id)
        yield article

    for headline in tree.css("h1"):
        ancestor = headline.parent
        depth = 0
        while ancestor is not None and depth < 6:
            if ancestor.mem_id not in seen:
                seen.add(ancestor.mem_id)
                yield ancestor
            ancestor = ancestor.parent
            depth += 1


def _node_descriptor(node: Node) -> str:
    tag = node.tag or "?"
    attrs = node.attributes or {}
    parts = [tag]
    node_id = (attrs.get("id") or "").strip()
    if node_id:
        parts.append(f"#{node_id}")
    classes = " ".join((attrs.get("class") or "").split())
    if classes:
        parts.append("." + ".".join(classes.split()))
    return "".join(parts)


def _join_blocks(blocks: Sequence[str]) -> str | None:
    if not blocks:
        return None
    text = "\n\n".join(blocks).strip()
    if not text:
        return None
    if len(text) > MAX_ARTICLE_LENGTH:
        text = text[:MAX_ARTICLE_LENGTH].rsplit(" ", 1)[0].strip()
    return text or None


def _is_valid_article(text: str, paragraphs: int) -> bool:
    if not text:
        return False
    if len(text) < 250 and paragraphs < 2:
        return False
    return True


def _collect_all_paragraphs(
    tree: HTMLParser,
    *,
    title: str | None,
) -> list[str]:
    seen: set[str] = set()
    stats = {"non_atomic_divs": 0, "direct_divs": 0, "atomic_divs": 0}
    blocks: list[str] = []

    for node in tree.css("p"):
        text = _normalize(node.text(separator=" ") or "")
        if text and not _is_date_like(text) and _should_include(text, title, seen):
            seen.add(text)
            blocks.append(text)

    for node in tree.css("div"):
        stats["non_atomic_divs"] += 1
        direct = _direct_text(node)
        if (
            direct
            and len(direct) >= _MIN_DIRECT_DIV_LENGTH
            and not _is_date_like(direct)
            and _should_include(direct, title, seen)
        ):
            seen.add(direct)
            blocks.append(direct)
            stats["direct_divs"] += 1

    if blocks:
        log.info(
            "tax_article fallback: %s divs with direct text out of %s checked",
            stats["direct_divs"],
            stats["non_atomic_divs"],
        )

    return blocks


def extract_tax_article(html: str, title: str | None = None) -> str | None:
    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    best: Node | None = None
    best_score = 0

    for candidate in _candidate_nodes(tree):
        score = _score_container(candidate)
        if score > best_score:
            best = candidate
            best_score = score

    stats = {"non_atomic_divs": 0, "direct_divs": 0, "atomic_divs": 0}

    if best is not None and best_score > 0:
        blocks = _collect_blocks(best, title=title, seen=set(), stats=stats)
        log.info(
            "tax_article best container %s score=%s blocks=%s atomic_divs=%s direct_divs=%s/%s",
            _node_descriptor(best),
            best_score,
            len(blocks),
            stats["atomic_divs"],
            stats["direct_divs"],
            stats["non_atomic_divs"],
        )
        combined = _join_blocks(blocks)
        if combined and _is_valid_article(combined, len(blocks)):
            return combined

    fallback_blocks = _collect_all_paragraphs(tree, title=title)
    fallback_text = _join_blocks(fallback_blocks)
    if fallback_text and _is_valid_article(fallback_text, len(fallback_blocks)):
        return fallback_text

    return None


__all__ = ["extract_tax_article"]
