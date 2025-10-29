from __future__ import annotations

import html
import re
from typing import Dict, List, Tuple

from services.text_cleanup import strip_redundant_preamble

PREVIEW_WITH_IMAGE = "with_image"
PREVIEW_WITHOUT_IMAGE = "without_image"

SUBSCRIBE_PROMO_TEXT = "Підпишись на IT Tax Radar"
SUBSCRIBE_PROMO_URL = "https://t.me/ITTaxRadar"

_SENTENCE_ENDINGS = (".", "!", "?", "…")

_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link"}


def _visible_length(text: str) -> int:
    if not text:
        return 0
    normalized = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    stripped = re.sub(r"<[^>]+>", "", normalized)
    return len(html.unescape(stripped))


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


def _append_block(base: str, block: str) -> str:
    base = base.strip()
    block = block.strip()
    if not base:
        return block
    if not block:
        return base
    return f"{base}\n\n{block}"


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

    def drop_leading_blanks(buf: list[str]) -> None:
        while buf and not buf[0].strip():
            buf.pop(0)

    drop_leading_blanks(remaining)

    while remaining:
        normalized = _normalize_for_compare(_strip_markdown_heading(remaining[0]))
        if normalized != title_norm:
            break
        remaining.pop(0)
        drop_leading_blanks(remaining)

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
    if limit <= 0:
        return ""

    if _visible_length(text) <= limit:
        return text

    visible_target = max(limit - 1, 0)
    result: List[str] = []
    open_tags: List[str] = []
    visible_count = 0
    i = 0
    length = len(text)

    while i < length and visible_count < visible_target:
        char = text[i]
        if char == "<":
            close_idx = text.find(">", i)
            if close_idx == -1:
                break
            tag_body = text[i + 1 : close_idx].strip()
            if tag_body:
                is_closing = tag_body.startswith("/")
                tag_name = tag_body[1:] if is_closing else tag_body
                tag_name = tag_name.split()[0].lower() if tag_name else ""
                is_self_closing = tag_body.endswith("/") or tag_name in _VOID_TAGS
                if is_closing:
                    if open_tags and open_tags[-1] == tag_name:
                        open_tags.pop()
                elif not is_self_closing and tag_name:
                    open_tags.append(tag_name)
            result.append(text[i : close_idx + 1])
            i = close_idx + 1
            continue
        if char == "&":
            semi_idx = text.find(";", i + 1)
            if semi_idx == -1:
                if visible_count + 1 > visible_target:
                    break
                result.append(char)
                visible_count += 1
                i += 1
                continue
            if visible_count + 1 > visible_target:
                break
            result.append(text[i : semi_idx + 1])
            visible_count += 1
            i = semi_idx + 1
            continue

        if visible_count + 1 > visible_target:
            break
        result.append(char)
        visible_count += 1
        i += 1

    truncated = "".join(result).rstrip()
    if visible_target > 0 and _visible_length(truncated) > visible_target:
        truncated = _truncate_html_preserving_tags(truncated, visible_target)

    if not truncated.endswith("…"):
        truncated = truncated.rstrip()
        if truncated and truncated[-1].isspace():
            truncated = truncated.rstrip()
        truncated += "…"

    for tag in reversed(open_tags):
        truncated += f"</{tag}>"

    return truncated


def _truncate_before_subscribe(main_text: str, subscribe_block: str, total_limit: int) -> str:
    subscribe = subscribe_block.strip()
    if not subscribe:
        return _truncate_html_preserving_tags(main_text, total_limit)

    main = main_text.strip()
    if not main:
        return _truncate_html_preserving_tags(subscribe_block, total_limit)

    joiner_len = 2
    available_for_main = total_limit - _visible_length(subscribe) - joiner_len
    if available_for_main < 0:
        return _truncate_html_preserving_tags(subscribe_block, total_limit)

    truncated_main = _truncate_html_preserving_tags(main, available_for_main)
    result = _append_block(truncated_main, subscribe_block)
    if _visible_length(result) <= total_limit:
        return result

    overflow = _visible_length(result) - total_limit
    truncated_main = _truncate_html_preserving_tags(truncated_main, max(available_for_main - overflow, 0))
    result = _append_block(truncated_main, subscribe_block)
    if _visible_length(result) <= total_limit:
        return result

    return _truncate_html_preserving_tags(subscribe_block, total_limit)


def build_preview_variants(*, title: str, review_md: str, link_url: str, tags: str) -> Dict[str, str]:
    """Return HTML strings for both preview types."""
    header = f"<b>{_escape_text(title.strip())}</b>"
    review_clean = _clean_review(review_md)
    review_clean = strip_redundant_preamble(review_clean, title)
    review_without_title = _drop_leading_title(review_clean, title)
    link_line = f"<a href=\"{_escape_attr(link_url)}\">читати далі>></a>"
    tags_line = _escape_text(tags.strip())
    subscribe_block = (
        f"<a href=\"{_escape_attr(SUBSCRIBE_PROMO_URL)}\">"
        f"<b>{_escape_text(SUBSCRIBE_PROMO_TEXT)}</b>"
        "</a>"
    )

    base_without_review = _append_block(
        _join_blocks(
            header,
            link_line,
            tags_line,
        ),
        subscribe_block,
    )
    available_for_review_with_image = 1024 - _visible_length(base_without_review) - len("\n\n")
    available_for_review_without_image = 4096 - _visible_length(base_without_review) - len("\n\n")

    def build_variant(base_limit: int, total_limit: int) -> str:
        limit = max(base_limit, 0)
        while True:
            review_candidate_md = _smart_trim(review_without_title, limit)
            review_candidate_html = _markdown_to_telegram_html(review_candidate_md)
            main_text = _join_blocks(
                header,
                review_candidate_html,
                link_line,
                tags_line,
            )
            text_candidate = _append_block(main_text, subscribe_block)
            candidate_length = _visible_length(text_candidate)
            if candidate_length <= total_limit or limit <= 0:
                if candidate_length <= total_limit:
                    return text_candidate
                if limit > 0:
                    overflow = candidate_length - total_limit
                    limit = max(limit - max(overflow, 1), 0)
                    continue

                if tags_line:
                    tags_tokens = tags_line.split()
                    while tags_tokens:
                        tags_tokens.pop()
                        candidate_tags = " ".join(tags_tokens)
                        main_text = _join_blocks(
                            header,
                            review_candidate_html,
                            link_line,
                            candidate_tags,
                        )
                        text_candidate = _append_block(main_text, subscribe_block)
                        if _visible_length(text_candidate) <= total_limit:
                            return text_candidate

                    main_text = _join_blocks(
                        header,
                        review_candidate_html,
                        link_line,
                    )
                    text_candidate = _append_block(main_text, subscribe_block)
                    if _visible_length(text_candidate) <= total_limit:
                        return text_candidate

                main_text = _join_blocks(
                    header,
                    review_candidate_html,
                    link_line,
                )
                return _truncate_before_subscribe(main_text, subscribe_block, total_limit)
            overflow = candidate_length - total_limit
            limit = max(limit - max(overflow, 1), 0)

    with_image_text = build_variant(available_for_review_with_image, 1024)
    without_image_text = build_variant(available_for_review_without_image, 4096)

    return {
        PREVIEW_WITH_IMAGE: with_image_text,
        PREVIEW_WITHOUT_IMAGE: without_image_text,
    }
