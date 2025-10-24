from __future__ import annotations

import re
from typing import Iterable

from selectolax.parser import HTMLParser, Node

DATE_RE = re.compile(r"\d{1,2}\s+[А-Яа-яІіЄєҐґ\.]+\.?\s+\d{4}\s+\d{2}:\d{2}|^\d{1,2}:\d{2}$")
STOP_PHRASES = ("теги", "поділитися", "останн")
WHITELIST_TAGS = {"p", "h2", "h3", "ul", "ol", "li", "blockquote"}
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

    if tag in WHITELIST_TAGS:
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


__all__ = ["extract_nbu_body", "is_reliable_nbu_body"]
