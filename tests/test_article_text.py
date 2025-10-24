import sys
import os
from textwrap import dedent

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.article_text import extract_article_text  # noqa: E402


HTML_WITH_ARTICLE = dedent(
    """
    <html>
      <body>
        <div class="page">
          <article class="article__content">
            <header><h1>На ринку небанківських фінансових послуг з’явилися два нові гравці</h1></header>
            <div class="article__meta">20 жовтня 2025</div>
            <div class="article__text">
              <p>Національний банк України видав дві нові ліцензії небанківським фінансовим установам.</p>
              <p>АТ «ФК «Портал» отримало право на кредитування, факторинг, фінлізинг та гарантії, а також ліцензію на операції з валютними цінностями в готівковій формі.</p>
              <p>ТОВ «ФК «Профіт Фінанс» може надавати послугу факторингу. Обидві компанії набули статусу фінансових установ одразу після отримання ліцензій.</p>
            </div>
          </article>
        </div>
      </body>
    </html>
    """
)


HTML_WITHOUT_P_TAGS = dedent(
    """
    <html>
      <body>
        <main>
          <section class="news__content">
            <div>Перше речення про рішення регулятора.</div>
            <div>Другий абзац пояснює, які саме ліцензії надано.</div>
          </section>
        </main>
      </body>
    </html>
    """
)


HTML_WITH_STOP_SECTION = dedent(
    """
    <html>
      <body>
        <main>
          <article>
            <h1>Виступ Голови Національного банку</h1>
            <div>11 вер. 2025 14:11</div>
            <div>
              <p>Доброго дня, шановні колеги!</p>
              <h3>Інфляція сповільнюється</h3>
              <p>Ми фіксуємо подальше зниження інфляційних очікувань.</p>
            </div>
            <div class="share">
              <span>Поділитися</span>
            </div>
          </article>
        </main>
      </body>
    </html>
    """
)


HTML_WITH_UNRELATED_HEADLINE = dedent(
    """
    <html>
      <body>
        <div class="page">
          <header>
            <h1>Офіційний сайт НБУ</h1>
            <nav>
              <a>Головна</a>
              <a>Поділитися</a>
            </nav>
          </header>
          <div class="layout">
            <div class="article-card">
              <h1>Виступ Голови Національного банку</h1>
              <div class="meta">23 жовт. 2025 14:13</div>
              <div class="content">
                <div>
                  <p>Добрий день, шановні колеги!</p>
                </div>
                <div>
                  <h3>Інфляція сповільнюється</h3>
                </div>
                <div>
                  <p>Ми фіксуємо подальше зниження інфляційних очікувань.</p>
                </div>
              </div>
              <footer>
                <span>Теги: монетарна політика</span>
              </footer>
            </div>
            <aside>
              <h2>Останні новини</h2>
              <ul>
                <li>Новина 1</li>
              </ul>
            </aside>
          </div>
        </div>
      </body>
    </html>
    """
)


HTML_WITH_NESTED_WRAPPER = dedent(
    """
    <html>
      <body>
        <main>
          <article>
            <h1>Виступ Голови Національного банку</h1>
            <div class="meta">
              <span>23 жовт. 2025 14:13</span>
            </div>
            <div class="wrapper">
              <section>
                <div><p>Добрий день, шановні колеги!</p></div>
                <div><h3>Інфляція сповільнюється</h3></div>
                <div><p>Ми фіксуємо подальше зниження інфляційних очікувань.</p></div>
              </section>
            </div>
            <footer>
              <span>Останні новини</span>
            </footer>
          </article>
        </main>
      </body>
    </html>
    """
)


HTML_WITHOUT_DATE_BLOCK = dedent(
    """
    <html>
      <body>
        <article>
          <h1>Нова постанова</h1>
          <div class="lead">
            <p>Перший абзац без окремої дати.</p>
          </div>
          <div>
            <p>Другий абзац з уточненнями.</p>
          </div>
          <div class="tags">Теги</div>
        </article>
      </body>
    </html>
    """
)


def test_extract_article_text_collects_paragraphs():
    text = extract_article_text(HTML_WITH_ARTICLE)
    assert "Національний банк України" in text
    assert text.count("\n\n") == 2


def test_extract_article_text_falls_back_to_block_text():
    text = extract_article_text(HTML_WITHOUT_P_TAGS)
    assert "Перше речення" in text
    assert "Другий абзац" in text


def test_extract_article_text_stops_before_related_sections():
    text = extract_article_text(HTML_WITH_STOP_SECTION)
    assert "Доброго дня" in text
    assert "Інфляція сповільнюється" in text
    assert "Поділитися" not in text


def test_extract_article_text_skips_unrelated_headline():
    text = extract_article_text(HTML_WITH_UNRELATED_HEADLINE)
    assert "Добрий день" in text
    assert "Інфляція сповільнюється" in text
    assert "Офіційний сайт" not in text


def test_extract_article_text_handles_nested_wrapper():
    text = extract_article_text(HTML_WITH_NESTED_WRAPPER)
    assert "Добрий день" in text
    assert "Інфляція сповільнюється" in text
    assert "Останні новини" not in text


def test_extract_article_text_works_without_explicit_date():
    text = extract_article_text(HTML_WITHOUT_DATE_BLOCK)
    assert "Перший абзац" in text
    assert "Другий абзац" in text
