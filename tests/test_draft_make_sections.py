import sys
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.post_sections import split_post_sections  # noqa: E402


def test_split_sections_handles_multiline_blocks():
    payload = """Довгий пост:
    Перший абзац.

    Другий абзац.

    Короткий пост:
    Стислий підсумок."""

    sections = split_post_sections(payload)

    assert sections.long == "Перший абзац.\n\nДругий абзац."
    assert sections.short == "Стислий підсумок."


def test_split_sections_supports_inline_headers():
    payload = "Довгий пост: Деталі рішення.\nКороткий пост – Коротко."  # noqa: E501

    sections = split_post_sections(payload)

    assert sections.long == "Деталі рішення."
    assert sections.short == "Коротко."


def test_split_sections_without_headings_returns_body():
    payload = "Просто текст без структурованих розділів."

    sections = split_post_sections(payload)

    assert sections.long == "Просто текст без структурованих розділів."
    assert sections.short is None


def test_split_sections_falls_back_to_short_when_long_missing():
    payload = "Короткий пост: Лаконічний варіант."

    sections = split_post_sections(payload)

    assert sections.long == "Лаконічний варіант."
    assert sections.short == "Лаконічний варіант."
