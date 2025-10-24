from __future__ import annotations

import html
from typing import Dict

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


def build_preview_variants(*, title: str, review_md: str, link_url: str, tags: str) -> Dict[str, str]:
    """Return HTML strings for both preview types."""
    header = f"<b>{_escape_text(title.strip())}</b>"
    review = _escape_text(_clean_review(review_md))
    link_line = f"<a href=\"{_escape_attr(link_url)}\">читати далі</a>"
    tags_line = _escape_text(tags.strip())

    base_without_review = _join_blocks(header, link_line, tags_line)
    available_for_review_with_image = 1024 - len(base_without_review) - len("\n\n")
    available_for_review_without_image = 4096 - len(base_without_review) - len("\n\n")

    review_for_image = _smart_trim(review, available_for_review_with_image)
    review_for_text = _smart_trim(review, available_for_review_without_image)

    with_image_text = _join_blocks(header, review_for_image, link_line, tags_line)
    without_image_text = _join_blocks(header, review_for_text, link_line, tags_line)

    # Safety trimming in case rounding produced overflow because of missing review block
    if len(with_image_text) > 1024:
        review_for_image = _smart_trim(review_for_image, available_for_review_with_image - (len(with_image_text) - 1024))
        with_image_text = _join_blocks(header, review_for_image, link_line, tags_line)

    if len(without_image_text) > 4096:
        review_for_text = _smart_trim(review_for_text, available_for_review_without_image - (len(without_image_text) - 4096))
        without_image_text = _join_blocks(header, review_for_text, link_line, tags_line)

    if len(with_image_text) > 1024:
        with_image_text = with_image_text[:1021].rstrip()
        if not with_image_text.endswith("…"):
            with_image_text += "…"

    if len(without_image_text) > 4096:
        without_image_text = without_image_text[:4093].rstrip()
        if not without_image_text.endswith("…"):
            without_image_text += "…"

    return {
        PREVIEW_WITH_IMAGE: with_image_text,
        PREVIEW_WITHOUT_IMAGE: without_image_text,
    }
