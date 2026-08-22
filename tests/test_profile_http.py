"""Listing-title extraction from the static Carousell profile HTML - this is what
gives the description generator real product context instead of just the bio."""
from studio.profile_http import _extract_listing_titles


def test_extracts_seller_listing_titles():
    html = (
        '{"listings":['
        '{"title":"USED AIRCON CLEARANCE DEAL"},'
        r'{"title":"Mission complete for HDB / BTO Installation"},'
        '{"title":"12.12 MEGA AIRCON SALE"}'
        ']}'
    )
    titles = _extract_listing_titles(html)
    assert "USED AIRCON CLEARANCE DEAL" in titles
    assert "Mission complete for HDB / BTO Installation" in titles  # / decoded
    assert "12.12 MEGA AIRCON SALE" in titles


def test_skips_chrome_and_dedupes():
    html = ('{"title":"Recommended"}{"title":"Search"}{"title":"Categories"}'
            '{"title":"Chemical Wash Service"}{"title":"Chemical Wash Service"}')
    titles = _extract_listing_titles(html)
    assert titles == ["Chemical Wash Service"]   # chrome dropped, deduped


def test_respects_limit():
    html = "".join(f'{{"title":"Aircon Listing Number {i}"}}' for i in range(10))
    assert len(_extract_listing_titles(html, limit=6)) == 6


def test_empty_on_no_listings():
    assert _extract_listing_titles("<html>no json here</html>") == []
    assert _extract_listing_titles("") == []
