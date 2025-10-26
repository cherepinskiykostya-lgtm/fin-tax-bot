from services.text_utils import normalize_title, remove_subscribe_promos


def test_normalize_title_collapses_whitespace():
    raw_title = "  21 жовтня 2025\n\tЗвільнення мобілізованих   ФОП   "

    assert normalize_title(raw_title) == "21 жовтня 2025 Звільнення мобілізованих ФОП"


def test_remove_subscribe_promos_keeps_article_text():
    text = (
        "Актуальна інформація про пільги.\n"
        "Підпишись на IT Tax Radar (https://t.me/ITTaxRadar)\n"
        "[**Підпишись на IT Tax Radar**](https://t.me/ITTaxRadar)\n"
        "Висновок без закликів."
    )

    assert remove_subscribe_promos(text) == "Актуальна інформація про пільги.\nВисновок без закликів."
