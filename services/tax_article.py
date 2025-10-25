from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from selectolax.parser import HTMLParser, Node

log = logging.getLogger("bot")

WHITELIST_TAGS = {
    "p",
    "div",
    "h2",
    "h3",
    "ul",
    "ol",
    "li",
    "blockquote",
    "table",
    "tr",
    "td",
}
STOP_PHRASES = (
    "поділитися",
    "поширити",
    "останн",
    "читайте також",
    "теги",
    "корисні посилання",
)
DATE_PATTERN = re.compile(
    r"\b\d{1,2}\.\d{2}\.\d{4}\b"
    r"|\b\d{1,2}\s+(?:січня|лютого|березня|квітня|травня|червня|липня|"
    r"серпня|вересня|жовтня|листопада|грудня)(?:\s+\d{4})?\s*(?:року)?\b",
    flags=re.IGNORECASE,
)
DATE_ONLY_PATTERN = re.compile(
    r"^\s*(?:\d{1,2}\.\d{2}\.\d{4}"
    r"|\d{1,2}\s+(?:січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня)"
    r"(?:\s+\d{4})?\s*(?:року)?)\s*$",
    flags=re.IGNORECASE,
)
WORDS_PATTERN = re.compile(r"[\w\u0400-\u04FF]{3,}")


@dataclass
class Block:
    text: str
    tag: str


@dataclass
class CollectionResult:
    blocks: list[Block]
    paragraphs: int
    stop_reason: Optional[str]


def _normalize_spaces(text: str) -> str:
    return " ".join(text.split()).strip()


def _has_whitelisted_descendant(node: Node) -> bool:
    child = node.child
    while child is not None:
        tag = (child.tag or "").lower()
        if tag and tag in WHITELIST_TAGS:
            return True
        if _has_whitelisted_descendant(child):
            return True
        child = child.next
    return False


def _is_atomic_div(node: Node) -> bool:
    if (node.tag or "").lower() != "div":
        return False
    return not _has_whitelisted_descendant(node)


def _score_container(node: Node) -> int:
    score = 0
    for el in node.traverse():
        tag = (el.tag or "").lower()
        if tag not in WHITELIST_TAGS:
            continue
        if tag == "div" and not _is_atomic_div(el):
            continue
        if tag in {"tr", "td"} and _has_table_ancestor(el):
            continue
        text = _normalize_spaces(el.text(separator=" ") or "")
        if text:
            score += len(text)
    return score


def _has_table_ancestor(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        tag = (parent.tag or "").lower()
        if tag == "table":
            return True
        parent = parent.parent
    return False


def _contains_node(container: Node, target: Node | None) -> bool:
    if target is None:
        return False
    current = target
    while current is not None:
        if current.mem_id == container.mem_id:
            return True
        current = current.parent
    return False


def _candidate_containers(tree: HTMLParser, headline: Node | None) -> list[Node]:
    seen: set[int] = set()
    candidates: list[Node] = []

    if headline is not None:
        parent = headline.parent
        depth = 0
        while parent is not None and depth < 10:
            if parent.mem_id not in seen:
                seen.add(parent.mem_id)
                candidates.append(parent)
            parent = parent.parent
            depth += 1

    for selector in ("article", "main", '[role="main"]', "section"):
        for node in tree.css(selector):
            if node.mem_id not in seen:
                seen.add(node.mem_id)
                candidates.append(node)

    if headline is not None:
        ancestors: list[Node] = []
        parent = headline.parent
        while parent is not None:
            ancestors.append(parent)
            parent = parent.parent

        for ancestor in ancestors:
            child = ancestor.child
            siblings_added = 0
            while child is not None and siblings_added < 6:
                tag = (child.tag or "").lower()
                if tag in {"div", "section", "article"} and child.mem_id not in seen:
                    seen.add(child.mem_id)
                    candidates.append(child)
                    siblings_added += 1
                child = child.next

    main_like: list[Node] = []
    for node in candidates:
        tag = (node.tag or "").lower()
        if tag in {"main", "article"}:
            main_like.append(node)

    for container in main_like:
        child = container.child
        added = 0
        while child is not None and added < 8:
            tag = (child.tag or "").lower()
            if tag in {"div", "section", "article"} and child.mem_id not in seen:
                seen.add(child.mem_id)
                candidates.append(child)
                added += 1
            child = child.next

    return candidates


def _best_container(tree: HTMLParser, headline: Node | None) -> tuple[Node | None, int]:
    candidates = _candidate_containers(tree, headline)
    best: Node | None = None
    best_score = 0

    prioritized = [node for node in candidates if _contains_node(node, headline)]
    pool = prioritized or candidates

    for node in pool:
        score = _score_container(node)
        if _contains_node(node, headline):
            score += 50
        if score > best_score:
            best = node
            best_score = score

    return best, best_score


def _table_rows(table: Node) -> Iterable[str]:
    for row in table.css("tr"):
        cells: list[str] = []
        for cell in row.css("th,td"):
            text = _normalize_spaces(cell.text(separator=" ") or "")
            if text:
                cells.append(text)
        if cells:
            yield " — ".join(cells)


def _iter_blocks(container: Node, after: Node | None) -> Iterable[Node]:
    start_id = after.mem_id if after is not None else None
    started = after is None

    for node in container.traverse():
        if node.mem_id == container.mem_id:
            continue
        if not started:
            if node.mem_id == start_id:
                started = True
            continue
        yield node


def _collect_blocks(
    container: Node,
    after: Node | None,
    headline_text: str,
) -> CollectionResult:
    blocks: list[Block] = []
    seen: set[str] = set()
    paragraphs = 0
    stop_reason: Optional[str] = None

    for node in _iter_blocks(container, after):
        tag = (node.tag or "").lower()
        if not tag:
            continue
        if tag in {"script", "style", "noscript"}:
            continue
        if tag not in WHITELIST_TAGS:
            continue
        if tag == "div" and not _is_atomic_div(node):
            continue
        if tag in {"tr", "td"} and _has_table_ancestor(node):
            continue

        if tag in {"ul", "ol"}:
            added_any = False
            for li in node.css("li"):
                li_text = _normalize_spaces(li.text(separator=" ") or "")
                if not li_text:
                    continue
                lowered_li = li_text.lower()
                if any(stop in lowered_li for stop in STOP_PHRASES):
                    stop_reason = next(stop for stop in STOP_PHRASES if stop in lowered_li)
                    return CollectionResult(blocks, paragraphs, stop_reason)
                bullet = f"• {li_text}"
                if bullet in seen:
                    continue
                seen.add(bullet)
                blocks.append(Block(bullet, "li"))
                added_any = True
            if added_any:
                continue

        if tag == "table":
            rows = list(_table_rows(node))
            if not rows:
                continue
            for row in rows:
                lowered = row.lower()
                if any(stop in lowered for stop in STOP_PHRASES):
                    stop_reason = next(stop for stop in STOP_PHRASES if stop in lowered)
                    return CollectionResult(blocks, paragraphs, stop_reason)
                if row in seen:
                    continue
                seen.add(row)
                blocks.append(Block(row, "table"))
            continue

        text_raw = node.text(separator=" ") or ""
        text = _normalize_spaces(text_raw)
        if not text:
            continue

        lowered = text.lower()
        if any(stop in lowered for stop in STOP_PHRASES):
            stop_reason = next(stop for stop in STOP_PHRASES if stop in lowered)
            break

        if headline_text and text.casefold() == headline_text:
            continue

        if tag == "li":
            bullet = f"• {text}"
            if bullet in seen:
                continue
            seen.add(bullet)
            blocks.append(Block(bullet, tag))
            continue

        if text in seen:
            continue
        seen.add(text)

        blocks.append(Block(text, tag))
        if tag in {"p", "div"}:
            paragraphs += 1

    return CollectionResult(blocks, paragraphs, stop_reason)


def _remove_leading_noise(blocks: list[Block]) -> tuple[list[Block], int]:
    if not blocks:
        return blocks, 0

    adjusted_paragraphs = sum(1 for block in blocks if block.tag in {"p", "div"})

    while blocks:
        first = blocks[0]
        if DATE_ONLY_PATTERN.match(first.text):
            if first.tag in {"p", "div"}:
                adjusted_paragraphs -= 1
            blocks.pop(0)
            continue
        break

    return blocks, adjusted_paragraphs


def _join_blocks(blocks: list[Block]) -> str:
    if not blocks:
        return ""
    parts = [block.text.strip() for block in blocks if block.text.strip()]
    text = "\n\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _first_words_match(text: str, html: str) -> bool:
    words = WORDS_PATTERN.findall(text.lower())
    if not words:
        return False
    sample = words[:10]
    if not sample:
        return False
    html_lower = html.lower()
    matches = sum(1 for word in sample if word in html_lower)
    required = max(3, len(sample) // 2)
    return matches >= required


def _is_valid(text: str, paragraphs: int, html: str) -> bool:
    if not text:
        return False
    if len(text) < 250 and paragraphs < 2:
        return False
    return _first_words_match(text, html)


def _find_date_node(container: Node, headline: Node | None) -> Node | None:
    if headline is None:
        return None
    seen_headline = False
    for node in container.traverse():
        if node.mem_id == container.mem_id:
            continue
        if node.mem_id == headline.mem_id:
            seen_headline = True
            continue
        if not seen_headline:
            continue
        if node.tag is None:
            continue
        text = _normalize_spaces(node.text(separator=" ") or "")
        if not text:
            continue
        if DATE_PATTERN.search(text):
            return node
    return None


def _all_paragraphs(tree: HTMLParser) -> tuple[str, int, int] | None:
    root = tree.root
    if root is None:
        return None

    seen: set[str] = set()
    blocks: list[tuple[str, str]] = []

    def gather(tags: set[str]) -> list[tuple[str, str]]:
        gathered: list[tuple[str, str]] = []
        for node in root.traverse():
            tag = (node.tag or "").lower()
            if tag not in tags:
                continue
            if tag == "div" and not _is_atomic_div(node):
                continue
            text = _normalize_spaces(node.text(separator=" ") or "")
            if not text:
                continue
            lowered = text.lower()
            if any(stop in lowered for stop in STOP_PHRASES):
                continue
            if text in seen:
                continue
            seen.add(text)
            gathered.append((text, tag))
        return gathered

    blocks.extend(gather({"p"}))
    if not blocks:
        seen.clear()
        blocks.extend(gather({"div"}))
    else:
        blocks.extend(gather({"div"}))

    if not blocks:
        return None

    paragraph_count = sum(1 for _, tag in blocks if tag == "p")
    div_count = sum(1 for _, tag in blocks if tag == "div")
    combined = "\n\n".join(text for text, _ in blocks).strip()
    if not combined:
        return None
    return combined, paragraph_count, div_count


def extract_tax_body(html: str) -> Optional[str]:
    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    headline = tree.css_first("h1")
    headline_text = _normalize_spaces(headline.text(separator=" ") or "") if headline else ""

    container, _ = _best_container(tree, headline)

    date_node = container and _find_date_node(container, headline)
    start_after = date_node or headline

    best_text: Optional[str] = None
    best_paragraphs = 0

    if container is not None and start_after is not None:
        result = _collect_blocks(container, start_after, headline_text)
        blocks, paragraphs = _remove_leading_noise(result.blocks)
        text = _join_blocks(blocks)
        if text:
            best_text = text
            best_paragraphs = paragraphs
            if _is_valid(text, paragraphs, html):
                log.info(
                    "tax body: from-date chars=%s paragraphs=%s stop=%s",
                    len(text),
                    paragraphs,
                    result.stop_reason or "-",
                )
                return text

    if container is not None:
        fallback_result = _collect_blocks(container, None, headline_text)
        blocks, paragraphs = _remove_leading_noise(fallback_result.blocks)
        text = _join_blocks(blocks)
        if text:
            if _is_valid(text, paragraphs, html):
                log.info(
                    "tax body: container-scored chars=%s paragraphs=%s stop=%s",
                    len(text),
                    paragraphs,
                    fallback_result.stop_reason or "-",
                )
                return text
            if best_text is None or len(text) > len(best_text):
                best_text = text
                best_paragraphs = paragraphs

    fallback = _all_paragraphs(tree)
    if fallback:
        text, paragraph_count, div_count = fallback
        log.info(
            "tax body: fell back to all <p>/<div> chars=%s paragraphs=%s div_blocks=%s",
            len(text),
            paragraph_count,
            div_count,
        )
        if paragraph_count == 0 and div_count > 0:
            log.info("tax body: fallback had only div blocks")
        return text

    if best_text and _first_words_match(best_text, html):
        log.info(
            "tax body: weak result chars=%s paragraphs=%s", len(best_text), best_paragraphs
        )
        return best_text

    return None


__all__ = ["extract_tax_body"]
