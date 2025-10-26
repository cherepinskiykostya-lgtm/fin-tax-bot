import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.image_extract import extract_image  # noqa: E402


def test_extract_image_prefers_meta_absolute():
    html = '<html><head><meta property="og:image" content="https://example.com/photo.jpg"></head></html>'
    assert extract_image(html) == "https://example.com/photo.jpg"


def test_extract_image_handles_relative_meta_with_base():
    html = '<html><head><meta property="og:image" content="/images/pic.png"></head></html>'
    result = extract_image(html, base_url="https://tax.gov.ua/media/article.html")
    assert result == "https://tax.gov.ua/images/pic.png"


def test_extract_image_falls_back_to_img_data_src():
    html = '<img data-src="//cdn.example.org/assets/main.jpeg" />'
    assert extract_image(html, base_url="https://example.org/post") == "https://cdn.example.org/assets/main.jpeg"


def test_extract_image_chooses_best_from_srcset():
    html = '<img srcset="/img/small.jpg 320w, /img/large.jpg 1024w">'
    result = extract_image(html, base_url="https://example.com/news")
    assert result == "https://example.com/img/large.jpg"
