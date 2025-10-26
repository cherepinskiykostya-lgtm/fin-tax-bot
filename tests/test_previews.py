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


def test_preview_has_single_subscribe_promo():
    review_md = (
        "**Test title**\n\nParagraph body.\n\n"
        "[**Підпишись на IT Tax Radar**](https://t.me/ITTaxRadar)"
    )
    variants = build_preview_variants(
        title="Test title",
        review_md=review_md,
        link_url="https://example.com/article",
        tags="#example",
    )

    for html in variants.values():
        assert html.count("Підпишись на IT Tax Radar") == 1
