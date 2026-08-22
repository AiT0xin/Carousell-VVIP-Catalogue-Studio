"""Catalogue data models - category colours and merchant readiness."""
from catbuilder.models import (
    MerchantData,
    CatalogueSection,
    CatalogueJob,
    colour_for_category,
)


def test_colour_for_category_known_and_default():
    assert colour_for_category("Watches") == "#1A237E"
    assert colour_for_category("  watches ") == "#1A237E"   # case + whitespace insensitive
    assert colour_for_category("nonexistent-category") == "#C62828"  # default red


def test_at_handle():
    assert MerchantData(handle="foo").at_handle == "@foo"


def test_listing_image_paths_defaults_to_empty_list():
    m = MerchantData(handle="x")
    assert m.listing_image_paths == []


def test_is_ready_false_without_assets():
    m = MerchantData(handle="foo", display_name="Foo", description="A description.")
    # no avatar / qr paths on disk → not ready to render
    assert m.is_ready() is False


def test_all_merchants_flattens_sections():
    job = CatalogueJob(
        title="t",
        sections=[
            CatalogueSection("Autos", [MerchantData(handle="a"), MerchantData(handle="b")]),
            CatalogueSection("Goods", [MerchantData(handle="c")]),
        ],
    )
    assert [m.handle for m in job.all_merchants] == ["a", "b", "c"]
