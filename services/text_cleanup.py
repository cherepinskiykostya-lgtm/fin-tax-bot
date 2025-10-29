import re

__all__ = ["strip_redundant_preamble", "rebuild_draft_body_md"]


def _normalize_text_for_compare(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    normalized = re.sub(r"^[\-–—•:*]+\s*", "", normalized)
    return normalized


def _looks_like_ua_date(text: str) -> bool:
    months = (
        "січня",
        "лютого",
        "березня",
        "квітня",
        "травня",
        "червня",
        "липня",
        "серпня",
        "вересня",
        "жовтня",
        "листопада",
        "грудня",
    )
    pattern = r"\b\d{1,2}\s+(" + "|".join(months) + r")\s+\d{4}\b"
    return bool(re.search(pattern, text.lower()))


def strip_redundant_preamble(text: str, title: str) -> str:
    stripped_text = text.strip()
    if not stripped_text:
        return stripped_text

    lines = text.splitlines()
    cleaned: list[str] = []
    normalized_title = _normalize_text_for_compare(title)
    removing_header = True

    for line in lines:
        stripped_line = line.strip()

        if removing_header:
            if not stripped_line:
                continue

            normalized_line = _normalize_text_for_compare(stripped_line)

            if normalized_title and normalized_line == normalized_title:
                continue

            if _looks_like_ua_date(stripped_line):
                continue

            removing_header = False

        cleaned.append(line)

    return "\n".join(cleaned).strip()


def rebuild_draft_body_md(body_md: str, title: str, subscribe_md: str | None = None) -> str:
    """Recreate the draft body keeping title/promo but dropping duplicated header lines."""

    title_clean = (title or "").strip()
    title_line = f"**{title_clean}**" if title_clean else ""
    subscribe_block = (subscribe_md or "").strip()

    text = (body_md or "").strip()
    if not text:
        return ""

    remainder = text
    if title_line and remainder.startswith(title_line):
        remainder = remainder[len(title_line) :]
        remainder = remainder.lstrip("\n ")

    subscribe_present = False
    if subscribe_block:
        for suffix in (subscribe_block, "\n\n" + subscribe_block, "\n" + subscribe_block):
            if remainder.endswith(suffix):
                remainder = remainder[: -len(suffix)].rstrip()
                subscribe_present = True
                break

    cleaned_core = strip_redundant_preamble(remainder, title)

    parts: list[str] = []
    if title_line:
        parts.append(title_line)
    if cleaned_core:
        parts.append(cleaned_core)
    if subscribe_present:
        parts.append(subscribe_block)

    return "\n\n".join(parts).strip()
