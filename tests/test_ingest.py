"""Master-sheet ingest - the forgiving parser that harvests Carousell handles
out of a messy, mixed-content VVIP sheet (business names, slash-separated cells,
corporate suffixes). A CSV fixture stands in for the multi-sheet xlsx."""
from qrcheck.ingest import (
    load_master,
    category_from_pdf_name,
    _looks_like_handle,
    _biz_name_to_handle,
    _harvest_handles,
)


def test_category_from_pdf_name():
    assert category_from_pdf_name("SG_VVIP_Autos_June.pdf") == "Autos"
    assert category_from_pdf_name("goods_catalogue.pdf") == "Goods"
    assert category_from_pdf_name("Luxury edition.pdf") == "Luxury"
    assert category_from_pdf_name("random.pdf") is None


def test_looks_like_handle():
    assert _looks_like_handle("acmemotors")
    assert _looks_like_handle("the.car_shop")
    assert not _looks_like_handle("pte")        # corporate blocklist
    assert not _looks_like_handle("12345")      # all digits
    assert not _looks_like_handle("ab")         # too short
    assert not _looks_like_handle("has space")  # not a single token


def test_biz_name_to_handle():
    assert _biz_name_to_handle("ACME MOTORWORKS PTE LTD") == "acmemotorworks"
    assert _biz_name_to_handle("Acme Tints") == "acmetints"
    # collapses past the 35-char handle ceiling → not a usable handle
    assert _biz_name_to_handle("A Really Long Descriptive Company Name Here") is None


def test_harvest_single_and_multi():
    assert _harvest_handles("acmemotors") == ["acmemotors"]
    got = set(_harvest_handles("acmecarshades /Acmecarparts.com"))
    assert got == {"acmecarshades", "acmecarparts.com"}


def test_harvest_skips_banner():
    assert _harvest_handles("SG VVIP Merchants") == []
    assert _harvest_handles("Merchants as of June 2026") == []


def test_load_master_from_csv(tmp_path):
    csv = tmp_path / "master.csv"
    csv.write_text(
        "SG VVIP Merchants,,\n"
        "Merchants as of June,,\n"
        ",,\n"
        "ACME Motorworks Pte Ltd,acmemotorworks,\n"
        "Acme Tints,acmetints,\n"
    )
    mt = load_master(str(csv))
    assert {"acmemotorworks", "acmetints"} <= mt.handles
    assert len(mt) >= 2
