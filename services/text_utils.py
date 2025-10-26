import re


def normalize_title(raw_title: str) -> str:
    return " ".join(raw_title.split())


def remove_subscribe_promos(text: str) -> str:
    pattern = r"(?mi)^\s*[\[\(*_\-\s]*Підпишись на IT Tax Radar[^\n]*\n?"
    return re.sub(pattern, "", text).strip()
