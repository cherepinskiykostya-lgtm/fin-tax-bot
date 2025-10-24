import sys
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.summary import choose_summary  # noqa: E402


HTML_SAMPLE = """
<html><head>
<meta property=\"og:description\" content=\" Компанії отримали ліцензії. \" />
<meta name=\"description\" content=\"Резервний опис.\" />
</head>
<body>
  <article class=\"article__text\">
    <p>Перший абзац.</p>
    <p>Другий абзац.</p>
  </article>
</body>
</html>
"""


def test_choose_summary_prefers_provided_text():
    result = choose_summary("Новина", " Власний опис події. ", HTML_SAMPLE)
    assert result == "Власний опис події."


def test_choose_summary_uses_meta_when_summary_missing():
    result = choose_summary("Новина", None, HTML_SAMPLE)
    assert result == "Компанії отримали ліцензії."


def test_choose_summary_ignores_title_duplicates():
    result = choose_summary("Новина", "Новина", HTML_SAMPLE)
    assert result == "Компанії отримали ліцензії."


def test_choose_summary_falls_back_to_article_text_when_meta_missing():
    html = """
    <html><body><article><p>Перший факт.</p><p>Другий факт.</p></article></body></html>
    """
    result = choose_summary("Новина", None, html)
    assert "Перший факт." in result
