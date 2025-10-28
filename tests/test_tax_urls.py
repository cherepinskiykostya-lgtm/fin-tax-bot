from services.tax_urls import tax_print_url, tax_canonical_url


def test_tax_print_url_builds_print_version():
    url = "https://tax.gov.ua/media-tsentr/novini/945326.html"
    assert tax_print_url(url) == "https://tax.gov.ua/media-tsentr/novini/print-945326.html"


def test_tax_print_url_normalizes_existing_print_slug():
    url = "https://tax.gov.ua/media-tsentr/novini/print-55555"
    assert tax_print_url(url) == "https://tax.gov.ua/media-tsentr/novini/print-55555.html"


def test_tax_canonical_url_from_print_returns_canonical():
    url = "https://tax.gov.ua/media-tsentr/novini/print-945326.html"
    assert tax_canonical_url(url) == "https://tax.gov.ua/media-tsentr/novini/945326.html"


def test_tax_canonical_url_preserves_non_print_path():
    url = "https://tax.gov.ua/media-tsentr/novini/98765.html"
    assert tax_canonical_url(url) == "https://tax.gov.ua/media-tsentr/novini/98765.html"


def test_tax_canonical_url_ignores_non_tax_links():
    assert tax_canonical_url("https://example.com/print-1.html") is None
