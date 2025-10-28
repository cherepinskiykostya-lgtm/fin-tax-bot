import os
import sys

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.text_cleanup import strip_redundant_preamble  # noqa: E402


def test_strip_preamble_drops_repeated_date_and_title():
    title = "Податкова знижка: до повернення з бюджету задекларовано на 104,1 млн грн більше ніж минулого року"
    payload = """23 жовтня 2025
                        Податкова знижка: до повернення з бюджету задекларовано на 104,1 млн грн більше ніж минулого року

23 жовтня 2025
Податкова знижка: до повернення з бюджету задекларовано на 104,1 млн грн більше ніж минулого року

Протягом січня – вересня 2025 року українці задекларували до повернення з бюджету 565,1 млн грн податкової знижки."""

    cleaned = strip_redundant_preamble(payload, title)

    assert cleaned.startswith("Протягом січня – вересня 2025 року")
    assert "Податкова знижка" not in cleaned.splitlines()[0]


def test_strip_preamble_handles_single_date_header():
    payload = """23 жовтня 2025

Основний текст повідомлення."""

    cleaned = strip_redundant_preamble(payload, "Будь-який заголовок")

    assert cleaned == "Основний текст повідомлення."


def test_strip_preamble_keeps_regular_content():
    payload = """Перший абзац без службових рядків.

Другий абзац залишається на місці."""

    cleaned = strip_redundant_preamble(payload, "Заголовок не використовується")

    assert cleaned == payload
