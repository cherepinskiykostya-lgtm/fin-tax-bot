from __future__ import annotations

import re
from typing import Iterable

from selectolax.parser import HTMLParser, Node

DATE_RE = re.compile(r"\d{1,2}\s+[А-Яа-яІіЄєҐґ\.]+\.?\s+\d{4}\s+\d{2}:\d{2}|^\d{1,2}:\d{2}$")
STOP_PHRASES = ("теги", "поділитися", "останн")
WHITELIST_TAGS = {"p", "div", "h2", "h3", "ul", "ol", "li", "blockquote"}
MIN_BODY_LENGTH = 200


def _words_match(text: str, html: str) -> bool:
    html_lower = html.lower()
    words = [word for word in re.findall(r"[\w\u0400-\u04FF]{4,}", text.lower())]
    if not words:
        return False
    sample = words[:8]
    required = min(3, len(sample))
    matches = sum(1 for word in sample if word in html_lower)
    return matches >= required


def is_reliable_nbu_body(text: str | None, html: str | None) -> bool:
    if not text or not html:
        return False
    if len(text) < MIN_BODY_LENGTH:
        return False
    return _words_match(text, html)


def _iter_after_headline(headline: Node) -> Iterable[Node]:
    node = headline.next
    steps = 0
    start_node = None
    while node is not None and steps < 50:
        text = (node.text() or "").strip() if node.tag is not None else ""
        if text:
            if DATE_RE.search(text):
                start_node = node
                break
            if start_node is None:
                start_node = node
        node = node.next
        steps += 1

    if start_node is None:
        start_node = headline

    node = start_node.next
    hops = 0
    while node is not None and hops < 2000:
        yield node
        node = node.next
        hops += 1


def _collect_from_node(node: Node, seen: set[str]) -> list[str]:
    collected: list[str] = []
    tag = (node.tag or "").lower()
    targets = ",".join(sorted(WHITELIST_TAGS))

    if tag in WHITELIST_TAGS and (tag != "div" or _is_atomic_div(node)):
        nodes = [node]
    else:
        nodes = node.css(targets)

    for current in nodes:
        current_tag = (current.tag or "").lower()
        text = (current.text() or "").strip()
        if not text or text in seen:
            continue

        if current_tag in {"ul", "ol"}:
            for li in current.css("li"):
                li_text = (li.text() or "").strip()
                if li_text and li_text not in seen:
                    seen.add(li_text)
                    collected.append(f"• {li_text}")
        elif current_tag == "li":
            if text and text not in seen:
                seen.add(text)
                collected.append(f"• {text}")
        elif current_tag == "div":
            if not _is_atomic_div(current):
                continue
            seen.add(text)
            collected.append(text)
        else:
            seen.add(text)
            collected.append(text)

    return collected


def extract_nbu_body(html: str) -> str | None:
    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    headline = tree.css_first("h1")
    if headline is None:
        return None

    body_parts: list[str] = []
    seen: set[str] = set()
    for node in _iter_after_headline(headline):
        text = (node.text() or "").strip()
        lowered = text.lower()
        if lowered and any(stop in lowered for stop in STOP_PHRASES):
            break

        body_parts.extend(_collect_from_node(node, seen))

    body = "\n\n".join(part for part in body_parts if part).strip()
    if not is_reliable_nbu_body(body or None, html):
        return None
    return body or None


def _score_container(node: Node) -> int:
    """Оценить контейнер по суммарной длине текста белых тегов."""

    score = 0
    for el in node.traverse():
        tag = (el.tag or "").lower()
        if tag in WHITELIST_TAGS:
            if tag == "div" and not _is_atomic_div(el):
                continue
            text = (el.text() or "").strip()
            if text:
                score += len(text)
    return score


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


def extract_body_fallback_generic(
    html: str,
    min_len: int = MIN_BODY_LENGTH,
    max_len: int = 3500,
) -> str | None:
    """Жёсткий фолбек для любых статей: берём самый насыщенный текстом блок."""

    try:
        tree = HTMLParser(html)
    except Exception:
        return None

    candidates: list[Node] = []
    for sel in ("main", "article", '[role="main"]', '[itemprop="articleBody"]'):
        el = tree.css_first(sel)
        if el is not None:
            candidates.append(el)

    h1 = tree.css_first("h1")
    if h1 is not None and h1.parent is not None:
        candidates.append(h1.parent)

    if not candidates:
        candidates.extend(tree.css("div, section"))

    best: Node | None = None
    best_score = 0
    for candidate in candidates:
        score = _score_container(candidate)
        if score > best_score:
            best = candidate
            best_score = score

    if best is None or best_score == 0:
        parts: list[str] = []
        seen: set[str] = set()
        root = tree.root
        if root is not None:
            for el in root.traverse():
                tag = (el.tag or "").lower()
                if tag == "p" or (tag == "div" and _is_atomic_div(el)):
                    text = (el.text() or "").strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    parts.append(text)
        text = "\n\n".join(parts).strip()
        if len(text) >= min_len:
            return text[:max_len]
        return None

    parts: list[str] = []
    seen: set[str] = set()
    for el in best.traverse():
        tag = (el.tag or "").lower()
        if tag not in WHITELIST_TAGS:
            continue
        if tag == "div" and not _is_atomic_div(el):
            continue

        text = (el.text() or "").strip()
        if not text:
            continue

        lowered = text.lower()
        if any(stop in lowered for stop in STOP_PHRASES):
            break

        if tag in {"ul", "ol"}:
            for li in el.css("li"):
                li_text = (li.text() or "").strip()
                if not li_text or li_text in seen:
                    continue
                seen.add(li_text)
                parts.append(f"• {li_text}")
        elif tag == "li":
            if text in seen:
                continue
            seen.add(text)
            parts.append(f"• {text}")
        else:
            if text in seen:
                continue
            seen.add(text)
            parts.append(text)

    body = "\n\n".join(part for part in parts if part).strip()
    if len(body) < min_len:
        fallback_parts: list[str] = []
        seen_fallback: set[str] = set()
        for el in best.traverse():
            tag = (el.tag or "").lower()
            if tag == "p" or (tag == "div" and _is_atomic_div(el)):
                text = (el.text() or "").strip()
                if not text or text in seen_fallback:
                    continue
                seen_fallback.add(text)
                fallback_parts.append(text)
        fallback = "\n\n".join(fallback_parts).strip()
        if len(fallback) > len(body):
            body = fallback

    if not body:
        return None

    return body[:max_len]


__all__ = [
    "extract_nbu_body",
    "is_reliable_nbu_body",
    "extract_body_fallback_generic",
]
