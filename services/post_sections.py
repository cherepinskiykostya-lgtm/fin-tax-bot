from __future__ import annotations

import re
from dataclasses import dataclass


_SECTION_ALIASES = {
    "довгий пост": "long",
    "довгий допис": "long",
    "короткий пост": "short",
    "короткий допис": "short",
}


@dataclass(slots=True)
class PostSections:
    long: str
    short: str | None


def _normalize_lines(lines: list[str]) -> str:
    cleaned: list[str] = []
    previous_blank = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not previous_blank and cleaned and cleaned[-1] != "":
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(stripped)
        previous_blank = False
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned).strip()


def _match_section_header(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    if not stripped:
        return None, ""

    separators = (":", "—", "-", "–")
    label = stripped
    remainder = ""
    for sep in separators:
        if sep in stripped:
            before, after = stripped.split(sep, 1)
            label = before.strip()
            remainder = after.strip()
            break
    normalized_label = re.sub(r"\s+", " ", label.lower())
    section = _SECTION_ALIASES.get(normalized_label)
    if section:
        return section, remainder
    return None, ""


def split_post_sections(raw: str) -> PostSections:
    if not raw.strip():
        return PostSections(long="", short=None)

    lines = raw.splitlines()
    buffer: list[str] = []
    preamble: list[str] = []
    collected: dict[str, list[str]] = {}
    current_section: str | None = None

    def flush_buffer(target_section: str | None) -> None:
        nonlocal buffer
        if not buffer:
            return
        if target_section:
            collected[target_section] = list(buffer)
        else:
            preamble.extend(buffer)
        buffer = []

    for line in lines:
        section, remainder = _match_section_header(line)
        if section:
            flush_buffer(current_section)
            current_section = section
            if remainder:
                buffer.append(remainder)
            continue

        buffer.append(line)

    flush_buffer(current_section)
    if not current_section and buffer:
        preamble.extend(buffer)

    long_lines = collected.get("long") or preamble
    short_lines = collected.get("short")

    long_text = _normalize_lines(long_lines) if long_lines else ""
    short_text = _normalize_lines(short_lines) if short_lines else None

    if not long_text and short_text:
        long_text = short_text

    return PostSections(long=long_text, short=short_text)
