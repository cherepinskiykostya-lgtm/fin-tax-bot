from __future__ import annotations

import html
import re
from typing import Dict, List, Tuple

PREVIEW_WITH_IMAGE = "with_image"
PREVIEW_WITHOUT_IMAGE = "without_image"

_SENTENCE_ENDINGS = (".", "!", "?", "…")


def _clean_review(text: str) -> str:
    """Normalize whitespace but keep paragraph structure."""
    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if not line:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _smart_trim(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text

    truncated = text[:limit].rstrip()
    best = ""

    # Prefer finishing at sentence boundary.
    for ending in _SENTENCE_ENDINGS:
        idx = truncated.rfind(ending)
        if idx != -1 and idx >= int(limit * 0.4):
            best = truncated[: idx + 1].strip()
            break

    if not best:
        newline_idx = truncated.rfind("\n")
        if newline_idx != -1 and newline_idx >= int(limit * 0.3):
            best = truncated[:newline_idx].strip()

    if not best:
        space_idx = truncated.rfind(" ")
        if space_idx != -1:
            best = truncated[:space_idx].strip()

    if not best:
        best = truncated.strip()

    best = best.rstrip("-•")
    if not best:
        return ""

    if not best.endswith(_SENTENCE_ENDINGS):
        if not best.endswith("…"):
            best = best.rstrip("…")
            best = best + "…"

    return best


def _join_blocks(*blocks: str) -> str:
    filtered = [block.strip() for block in blocks if block and block.strip()]
    return "\n\n".join(filtered)


def _escape_text(text: str) -> str:
    return html.escape(text, quote=False)


def _escape_attr(value: str) -> str:
    return html.escape(value, quote=True)


def _normalize_for_compare(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _strip_markdown_heading(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^#+\s*", "", text)
    for marker in ("**", "__"):
        if text.startswith(marker) and text.endswith(marker) and len(text) > len(marker) * 2:
            text = text[len(marker) : -len(marker)]
            break
    if text.startswith("*") and text.endswith("*") and len(text) > 2:
        text = text[1:-1]
    if text.startswith("_") and text.endswith("_") and len(text) > 2:
        text = text[1:-1]
    return text.strip()


def _drop_leading_title(review: str, title: str) -> str:
    if not review.strip():
        return review.strip()

    lines = review.splitlines()
    title_norm = _normalize_for_compare(title)

    first_idx = None
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        if _normalize_for_compare(_strip_markdown_heading(line)) == title_norm:
            first_idx = idx
        break

    if first_idx is None:
        return review.strip()

    remaining = lines[first_idx + 1 :]
    while remaining and not remaining[0].strip():
        remaining.pop(0)
    return "\n".join(remaining).strip()


def _format_inline(text: str) -> str:
    result: List[str] = []
    plain: List[str] = []

    def flush_plain() -> None:
        if plain:
            result.append(_escape_text("".join(plain)))
            plain.clear()

    i = 0
    length = len(text)
    while i < length:
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end != -1:
                flush_plain()
                result.append(f"<b>{_format_inline(text[i + 2:end])}</b>")
                i = end + 2
                continue
        if text.startswith("__", i):
            end = text.find("__", i + 2)
            if end != -1:
                flush_plain()
                result.append(f"<b>{_format_inline(text[i + 2:end])}</b>")
                i = end + 2
                continue
        if text[i] == '*' and (i + 1) < length and text[i + 1] != ' ':
            end = text.find('*', i + 1)
            if end != -1:
                flush_plain()
                result.append(f"<i>{_format_inline(text[i + 1:end])}</i>")
                i = end + 1
                continue
        if text[i] == '_' and (i + 1) < length and text[i + 1] != ' ':
            prev = text[i - 1] if i > 0 else ''
            end = text.find('_', i + 1)
            if end != -1:
                after = text[end + 1] if (end + 1) < length else ''
                if prev.isalnum() or after.isalnum():
                    # Treat as plain underscore inside a word.
                    plain.append(text[i])
                    i += 1
                    continue
                flush_plain()
                result.append(f"<i>{_format_inline(text[i + 1:end])}</i>")
                i = end + 1
                continue
        if text[i] == '`':
            end = text.find('`', i + 1)
            if end != -1:
                flush_plain()
                result.append(f"<code>{_escape_text(text[i + 1:end])}</code>")
                i = end + 1
                continue
        if text[i] == '[':
            close = text.find(']', i + 1)
            if close != -1 and close + 1 < length and text[close + 1] == '(':
                end = text.find(')', close + 2)
                if end != -1:
                    flush_plain()
                    label = _format_inline(text[i + 1:close])
                    url = _escape_attr(text[close + 2:end])
                    result.append(f'<a href="{url}">{label}</a>')
                    i = end + 1
                    continue
        plain.append(text[i])
        i += 1

    flush_plain()
    return "".join(result)


def _flush_list(buffer: List[Tuple[str, str]], result: List[str]) -> None:
    if not buffer:
        return
    for marker, content in buffer:
        if marker:
            result.append(f"{marker} {content}")
        else:
            result.append(content)
    buffer.clear()


def _markdown_to_telegram_html(markdown: str) -> str:
    if not markdown.strip():
        return ""

    lines = markdown.splitlines()
    result: List[str] = []
    bullets: List[Tuple[str, str]] = []
    numbers: List[Tuple[str, str]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            _flush_list(bullets, result)
            _flush_list(numbers, result)
            if result and result[-1] != "":
                result.append("")
            continue

        if stripped.startswith(('- ', '* ')):
            _flush_list(numbers, result)
            bullets.append(("•", _format_inline(stripped[2:].strip())))
            continue

        number_match = re.match(r"(\d+)[\.)]\s+(.*)", stripped)
        if number_match:
            _flush_list(bullets, result)
            number = number_match.group(1)
            content = _format_inline(number_match.group(2).strip())
            numbers.append((f"{number}.", content))
            continue

        _flush_list(bullets, result)
        _flush_list(numbers, result)

        heading_match = re.match(r"#{1,6}\s+(.*)", stripped)
        if heading_match:
            result.append(f"<b>{_format_inline(heading_match.group(1).strip())}</b>")
            continue

        result.append(_format_inline(stripped))

    _flush_list(bullets, result)
    _flush_list(numbers, result)

    return "\n".join(result).strip()


def _truncate_html_preserving_tags(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    truncated = text[:limit]

    # Avoid cutting inside an HTML entity.
    last_amp = truncated.rfind("&")
    if last_amp != -1 and truncated.find(";", last_amp) == -1:
        truncated = truncated[:last_amp]

    # Avoid cutting inside an HTML tag.
    last_lt = truncated.rfind("<")
    last_gt = truncated.rfind(">")
    if last_lt > last_gt:
        truncated = truncated[:last_lt]

    # Track unclosed tags to close them at the end.
    open_tags: List[str] = []
    for match in re.finditer(r"<(/?)([a-zA-Z0-9]+)(?:\s[^>]*)?>", truncated):
        tag = match.group(2).lower()
        if match.group(1) == "/":
            if open_tags and open_tags[-1] == tag:
                open_tags.pop()
        else:
            if tag not in {"br"}:
                open_tags.append(tag)

    truncated = truncated.rstrip()
    if limit > 0 and not truncated.endswith("…"):
        if len(truncated) >= limit:
            truncated = truncated[: limit - 1]
            truncated = truncated.rstrip()
        truncated += "…"

    for tag in reversed(open_tags):
        closing = f"</{tag}>"
        if len(truncated) + len(closing) <= limit:
            truncated += closing
        else:
            truncated = re.sub(rf"<{tag}(?:\s[^>]*)?>[^<]*$", "", truncated).rstrip()

    return truncated[:limit]


def build_preview_variants(*, title: str, review_md: str, link_url: str, tags: str) -> Dict[str, str]:
    """Return HTML strings for both preview types."""
    header = f"<b>{_escape_text(title.strip())}</b>"
    review_clean = _clean_review(review_md)
    review_without_title = _drop_leading_title(review_clean, title)
    link_line = f"<a href=\"{_escape_attr(link_url)}\">читати далі</a>"
    tags_line = _escape_text(tags.strip())

    base_without_review = _join_blocks(header, link_line, tags_line)
    available_for_review_with_image = 1024 - len(base_without_review) - len("\n\n")
    available_for_review_without_image = 4096 - len(base_without_review) - len("\n\n")

    def build_variant(base_limit: int, total_limit: int) -> str:
        limit = max(base_limit, 0)
        while True:
            review_candidate_md = _smart_trim(review_without_title, limit)
            review_candidate_html = _markdown_to_telegram_html(review_candidate_md)
            text_candidate = _join_blocks(header, review_candidate_html, link_line, tags_line)
            if len(text_candidate) <= total_limit or limit <= 0:
                if len(text_candidate) > total_limit:
                    text_candidate = _truncate_html_preserving_tags(text_candidate, total_limit)
                return text_candidate
            overflow = len(text_candidate) - total_limit
            limit = max(limit - max(overflow, 1), 0)

    with_image_text = build_variant(available_for_review_with_image, 1024)
    without_image_text = build_variant(available_for_review_without_image, 4096)

    return {
        PREVIEW_WITH_IMAGE: with_image_text,
        PREVIEW_WITHOUT_IMAGE: without_image_text,
    }
