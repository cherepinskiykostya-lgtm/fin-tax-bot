import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.tax_urls import tax_print_url  # noqa: E402


def test_tax_print_url_from_slug_with_id():
    url = "https://tax.gov.ua/media-tsentr/novini/novij-servis-945326.html"
    assert tax_print_url(url) == "https://tax.gov.ua/media-tsentr/novini/print-945326.html"


def test_tax_print_url_handles_trailing_slash():
    url = "https://www.tax.gov.ua/media-tsentr/novini/pres-reliz-98765/"
    assert tax_print_url(url) == "https://www.tax.gov.ua/media-tsentr/novini/print-98765.html"


def test_tax_print_url_normalizes_existing_print_path():
    url = "https://tax.gov.ua/media-tsentr/novini/print-55555"
    assert tax_print_url(url) == "https://tax.gov.ua/media-tsentr/novini/print-55555.html"


def test_tax_print_url_returns_none_for_non_matching_paths():
    url = "https://tax.gov.ua/about/structure/"
    assert tax_print_url(url) is None


def test_tax_print_url_returns_none_when_id_missing():
    url = "https://tax.gov.ua/media-tsentr/novini/bez-nomeru/"
    assert tax_print_url(url) is None
