import os
import sys

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.text_cleanup import (  # noqa: E402
    rebuild_draft_body_md,
    strip_redundant_preamble,
    _looks_like_person_intro,
)


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


def test_strip_preamble_handles_markdown_wrapped_headers():
    title = "Податкова знижка: до повернення з бюджету задекларовано на 104,1 млн грн більше ніж минулого року"
    payload = """**23 жовтня 2025**
**{title}**

Основний текст новини.""".format(title=title)

    cleaned = strip_redundant_preamble(payload, title)

    assert cleaned == "Основний текст новини."


def test_strip_preamble_skips_title_with_punctuation_suffix():
    title = "Податкова знижка: до повернення з бюджету задекларовано на 104,1 млн грн більше ніж минулого року"
    payload = """23 жовтня 2025 —
{title}:

Основний текст новини.""".format(title=title)

    cleaned = strip_redundant_preamble(payload, title)

    assert cleaned == "Основний текст новини."


def test_rebuild_draft_body_md_removes_duplicates_and_keeps_promo():
    title = "ДПС і НБУ впроваджують новий підхід у комунікації з банками щодо валютного нагляду"
    promo = "[**Підпишись на IT Tax Radar**](https://t.me/ITTaxRadar)"
    body = f"""**{title}**

27 жовтня 2025
{title}

Основний текст новини.

{promo}"""

    rebuilt = rebuild_draft_body_md(body, title, promo)

    assert rebuilt == f"**{title}**\n\nОсновний текст новини.\n\n{promo}"


def test_rebuild_draft_body_md_handles_missing_body():
    title = "Заголовок"
    promo = "[**Підпишись на IT Tax Radar**](https://t.me/ITTaxRadar)"
    body = f"**{title}**\n\n{promo}"

    rebuilt = rebuild_draft_body_md(body, title, promo)

    assert rebuilt == f"**{title}**\n\n{promo}"


def test_rebuild_draft_body_md_without_promo():
    title = "Заголовок"
    body = f"**{title}**\n\n27 жовтня 2025\n\n{title}\n\nОсновний текст"

    rebuilt = rebuild_draft_body_md(body, title, None)

    assert rebuilt == f"**{title}**\n\nОсновний текст"


def test_looks_like_person_intro():
    """Test detection of person introductions."""
    # Should detect person intros
    assert _looks_like_person_intro("Леся Карнаух: текст статті")
    assert _looks_like_person_intro("В. о. Голови ДПС: описание")
    assert _looks_like_person_intro("Іван Петренко: кілька слів")
    
    # Should NOT detect as person intro
    assert not _looks_like_person_intro("текст без введення")
    assert not _looks_like_person_intro("це просто текст з точкою.")
    assert not _looks_like_person_intro("і це теж текст")
    assert not _looks_like_person_intro(":не правильний формат")


def test_strip_preamble_removes_date_and_person_intro():
    """Test that both dates and person intros are removed."""
    title = "Леся Карнаух: За 10 місяців місцеві бюджети отримали понад 403,2 млрд гривень"
    payload = """04 листопада 2025

                        Леся Карнаух: За 10 місяців місцеві бюджети отримали понад 403,2 млрд гривень

Місцеві бюджети України за період отримали понад 403,2 млрд гривень."""

    cleaned = strip_redundant_preamble(payload, title)

    # Should remove date and person intro
    assert "листопада" not in cleaned
    assert "Леся Карнаух" not in cleaned.split("\n")[0]
    # Should keep main content
    assert "Місцеві бюджети України" in cleaned