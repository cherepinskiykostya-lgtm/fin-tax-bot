import os
import sys
from textwrap import dedent

os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.tax_article import extract_tax_article  # noqa: E402


def test_extract_tax_article_handles_nested_divs():
    html = dedent(
        """
        <html>
          <body>
            <div class="page">
              <div class="wrapper">
                <div class="news__content">
                  <div class="block">
                    Перший абзац описує основні зміни в адмініструванні податків.
                  </div>
                  <div class="block">
                    Другий абзац містить деталі про впровадження нових сервісів для платників.
                  </div>
                </div>
              </div>
            </div>
          </body>
        </html>
        """
    )

    text = extract_tax_article(html)

    assert "Перший абзац" in text
    assert "Другий абзац" in text


def test_extract_tax_article_includes_direct_text_for_non_atomic_div():
    long_intro = " ".join(["Вступний" for _ in range(30)])
    html = dedent(
        f"""
        <html>
          <body>
            <main>
              <article>
                <h1>Нові підходи до звітності</h1>
                <div class="article__body">
                  <div class="lead">
                    {long_intro}
                    <p>Це додатковий блок пояснень.</p>
                  </div>
                  <div>
                    <p>Оновлені правила діють з початку наступного кварталу.</p>
                  </div>
                </div>
              </article>
            </main>
          </body>
        </html>
        """
    )

    text = extract_tax_article(html, title="Нові підходи до звітності")

    assert long_intro[:50] in text
    assert "Оновлені правила" in text


def test_extract_tax_article_fallback_collects_divs_with_text():
    long_text = " ".join(["Абзац" for _ in range(25)])
    second_text = " ".join(["Речення" for _ in range(20)])
    html = dedent(
        f"""
        <html>
          <body>
            <div class="layout">
              <div class="teaser">Короткі новини</div>
              <div class="content">
                <div>{long_text}</div>
                <div>{second_text}</div>
              </div>
            </div>
          </body>
        </html>
        """
    )

    text = extract_tax_article(html)

    assert text is not None
    assert long_text[:40] in text
    assert second_text[:40] in text
