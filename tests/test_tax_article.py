from services.tax_article import extract_tax_body


def test_extract_tax_body_basic():
    html = """
    <html>
      <body>
        <main>
          <article>
            <h1>Звільнення мобілізованих ФОП від сплати податків</h1>
            <div class="meta">21 жовтня 2025 року</div>
            <p><strong>21 жовтня 2025 року Президент України підписав закон, який звільняє мобілізованих фізичних осіб-підприємців від сплати податків.</strong></p>
            <p>Закон передбачає, що ФОП не сплачують податки протягом усього періоду служби, за умови подання підтвердних документів до податкового органу.</p>
            <ul>
              <li>Закон діє для всіх груп єдиного податку.</li>
              <li>Пільга поширюється на інші обов'язкові платежі.</li>
            </ul>
            <div class="share">Поділитися</div>
          </article>
        </main>
      </body>
    </html>
    """
    body = extract_tax_body(html)
    assert body is not None
    assert "Поділитися" not in body
    assert "• Закон діє для всіх груп єдиного податку." in body
    assert body.splitlines()[0].startswith("21 жовтня 2025 року Президент України")


def test_extract_tax_body_fallback_all_paragraphs():
    html = """
    <html>
      <body>
        <div>
          <h1>Повідомлення ДПС</h1>
          <p>Короткий коментар без достатньої довжини.</p>
        </div>
        <p>Додатковий абзац у кінці сторінки, який має бути включений у фолбек.</p>
      </body>
    </html>
    """
    body = extract_tax_body(html)
    assert body is not None
    assert "Повідомлення ДПС" not in body
    assert "Короткий коментар без достатньої довжини." in body
    assert "Додатковий абзац" in body
