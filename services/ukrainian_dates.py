from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:  # pragma: no cover - fallback for platforms without zoneinfo data
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:  # pragma: no cover
    KYIV_TZ = timezone.utc

_MONTH_VARIANTS: dict[int, tuple[str, ...]] = {
    1: ("січня", "січ", "січ."),
    2: ("лютого", "лют", "лют."),
    3: ("березня", "берез", "бер", "бер."),
    4: ("квітня", "квіт", "квіт."),
    5: ("травня", "трав", "трав."),
    6: ("червня", "черв", "черв."),
    7: ("липня", "лип", "лип."),
    8: ("серпня", "серп", "серп."),
    9: ("вересня", "верес", "вер", "вер."),
    10: ("жовтня", "жовт", "жов", "жовт."),
    11: ("листопада", "листоп", "лист", "лист."),
    12: ("грудня", "груд", "груд."),
}

_MONTHS: dict[str, int] = {}
for month, variants in _MONTH_VARIANTS.items():
    for variant in variants:
        normalized_variant = variant.replace(".", "").lower()
        _MONTHS[normalized_variant] = month


def parse_ukrainian_date(
    value: str,
    reference: datetime | None = None,
    tz: timezone = KYIV_TZ,
) -> datetime | None:
    """Parse Ukrainian textual date representations into :class:`datetime`.

    Supports ISO 8601 strings, dotted numeric dates, and day-month (in Ukrainian)
    combinations optionally followed by a time. When only time is provided the
    ``reference`` datetime is used to fill the date portion.
    """

    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    text = raw.lower()
    text = text.replace("сьогодні", "")
    text = re.sub(r"\s+вчора", "", text)
    text = re.sub(r"\s+р(\.|оку)?$", "", text)
    text = text.replace(" о ", " ")
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()

    iso_match = re.search(
        r"(\d{4}-\d{2}-\d{2}t\d{2}:\d{2}(?::\d{2})?(?:[+\-]\d{2}:?\d{2}|z)?)",
        text,
    )
    if iso_match:
        iso_value = iso_match.group(1).replace("z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt
        except ValueError:
            pass

    dotted = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if dotted:
        day, month, year = dotted.groups()
        hour = minute = 0
        time_match = re.search(r"(\d{1,2}):(\d{2})", text[dotted.end() :])
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
        try:
            return datetime(
                int(year),
                int(month),
                int(day),
                hour,
                minute,
                tzinfo=tz,
            )
        except ValueError:
            return None

    time_only = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*год\.?)?", text)
    if time_only:
        hour = int(time_only.group(1))
        minute = int(time_only.group(2))
        base = reference
        if base is None:
            base = datetime.now(tz)
        elif base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        else:
            base = base.astimezone(tz)
        try:
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None

    words = re.search(r"(\d{1,2})\s+([а-яіїєґ.]+)\s+(\d{4})", text)
    if words:
        day = int(words.group(1))
        month_name = words.group(2)
        normalized_month = month_name.replace(".", "").strip()
        year = int(words.group(3))
        month = _MONTHS.get(month_name) or _MONTHS.get(normalized_month)
        if month is None:
            return None
        hour = minute = 0
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
        try:
            return datetime(year, month, day, hour, minute, tzinfo=tz)
        except ValueError:
            return None

    return None


__all__ = ["KYIV_TZ", "parse_ukrainian_date"]
