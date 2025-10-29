import os
import sys

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("WEBHOOK_SECRET", "dummy")
os.environ.setdefault("CHANNEL_ID", "0")

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from services.previews import (  # noqa: E402
    PREVIEW_WITH_IMAGE,
    PREVIEW_WITHOUT_IMAGE,
    build_preview_variants,
)


@pytest.mark.parametrize("variant_key", [PREVIEW_WITH_IMAGE, PREVIEW_WITHOUT_IMAGE])
def test_preview_contains_subscribe_promo(variant_key):
    variants = build_preview_variants(
        title="Test title",
        review_md="**Test title**\n\nSome body text.",
        link_url="https://example.com/article",
        tags="#example",
    )

    subscribe_link = '<a href="https://t.me/ITTaxRadar"><b>Підпишись на IT Tax Radar</b></a>'
    assert subscribe_link in variants[variant_key]


def test_preview_drops_duplicate_header_lines():
    duplicated = (
        "**ДПС і НБУ впроваджують новий підхід**\n\n"
        "27 жовтня 2025\n"
        "ДПС і НБУ впроваджують новий підхід\n\n"
        "27 жовтня 2025\n"
        "ДПС і НБУ впроваджують новий підхід\n\n"
        "Основний текст про ініціативу."
    )

    variants = build_preview_variants(
        title="ДПС і НБУ впроваджують новий підхід",
        review_md=duplicated,
        link_url="https://example.com/article",
        tags="#UkraineTax",
    )

    for text in variants.values():
        assert text.count("27 жовтня 2025") == 0
        assert text.count("ДПС і НБУ впроваджують новий підхід") == 1
