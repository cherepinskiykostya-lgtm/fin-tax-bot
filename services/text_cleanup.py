import re

__all__ = ["strip_redundant_preamble"]


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
