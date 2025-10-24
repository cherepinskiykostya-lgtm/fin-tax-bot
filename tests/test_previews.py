import pytest

from services.previews import build_preview_variants, PREVIEW_WITH_IMAGE, PREVIEW_WITHOUT_IMAGE


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
