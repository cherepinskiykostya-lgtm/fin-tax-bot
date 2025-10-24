import os
import sys
from textwrap import dedent

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.nbu_article import extract_nbu_body  # noqa: E402


HTML_NBU_SAMPLE = dedent(
    """
    <html>
      <body>
        <article>
          <h1>Виступ Голови Національного банку</h1>
          <div class="meta">23 жовт. 2025 14:13</div>
          <div class="content">
            <p>Добрий день, шановні колеги! Сьогодні ми говоримо про ключові рішення, які Національний банк ухвалив для
            забезпечення стабільності фінансової системи під час затяжної повномасштабної війни. Ми розуміємо, наскільки
            важливими є чітка комунікація та прозорість, тож надамо детальні пояснення щодо кожного кроку.</p>
            <h3>Інфляція сповільнюється</h3>
            <p>Ми фіксуємо подальше зниження інфляційних очікувань бізнесу й домогосподарств, що дозволяє нам коригувати
            монетарні інструменти без ризику розбалансування цінової стабільності. Саме тому правління одностайно підтримало
            збереження облікової ставки на поточному рівні.</p>
            <ul>
              <li>Продовжуємо працювати з міжнародними партнерами для забезпечення стабільного курсу.</li>
              <li>Підсилюємо співпрацю з банківським сектором, аби кредитування відновлювалося швидше.</li>
            </ul>
          </div>
          <div class="share">
            <span>Поділитися</span>
          </div>
        </article>
      </body>
    </html>
    """
)


HTML_NBU_TOO_SHORT = dedent(
    """
    <html>
      <body>
        <article>
          <h1>Коротка новина</h1>
          <div>23 жовт. 2025 14:13</div>
          <p>Одне речення.</p>
          <div class="tags">Теги</div>
        </article>
      </body>
    </html>
    """
)


def test_extract_nbu_body_collects_content_blocks():
    body = extract_nbu_body(HTML_NBU_SAMPLE)
    assert body is not None
    assert "Добрий день, шановні колеги!" in body
    assert "Інфляція сповільнюється" in body
    assert "• Продовжуємо працювати" in body
    assert "Поділитися" not in body


def test_extract_nbu_body_returns_none_for_too_short_articles():
    body = extract_nbu_body(HTML_NBU_TOO_SHORT)
    assert body is None
