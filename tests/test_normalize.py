"""Handle / URL normalization and classification - the single source of truth
for "is this a profile link and, if so, whose?"."""
from qrcheck.normalize import (
    normalize_handle,
    canonicalize_url,
    is_cta_url,
    is_shortlink,
    handle_from_profile_url,
    profile_url_for,
    classify_url,
)
from qrcheck.models import QRClass


def test_normalize_handle():
    assert normalize_handle("@AcmeMotors ") == "acmemotors"
    assert normalize_handle("  @ABC.def_ ") == "abc.def_"
    assert normalize_handle(None) == ""
    assert normalize_handle("") == ""
    # idempotent
    assert normalize_handle(normalize_handle("@Foo")) == "foo"


def test_handle_from_profile_url_canonical():
    assert handle_from_profile_url("https://www.carousell.sg/u/acmemotors/") == "acmemotors"
    assert handle_from_profile_url("https://carousell.sg/u/Foo/") == "foo"


def test_handle_from_profile_url_bare_path():
    # carousell.com/<handle> without /u/
    assert handle_from_profile_url("https://www.carousell.com/acmegamestore") == "acmegamestore"


def test_handle_from_profile_url_rejects_non_profiles():
    # reserved site section, not a username
    assert handle_from_profile_url("https://www.carousell.sg/search") is None
    # CTA host is not a profile host
    assert handle_from_profile_url("https://college.carousell.com/top-auto/") is None
    assert handle_from_profile_url(None) is None


def test_profile_url_for():
    assert profile_url_for("Foo") == "https://www.carousell.sg/u/foo/"


def test_is_shortlink_and_cta():
    assert is_shortlink("https://caro.sl/xyz")
    assert not is_shortlink("https://carousell.sg/u/x/")
    assert is_cta_url("https://wa.me/6591234567")
    assert is_cta_url("https://college.carousell.com/x")
    assert not is_cta_url("https://carousell.sg/u/x/")


def test_canonicalize_url():
    assert canonicalize_url("HTTPS://WWW.Carousell.SG/u/Foo/") == "https://www.carousell.sg/u/Foo"
    assert canonicalize_url("carousell.sg/x") == "https://carousell.sg/x"
    assert canonicalize_url("") == ""


def test_classify_url():
    assert classify_url("https://www.carousell.sg/u/foo/") == (QRClass.MERCHANT, "foo")
    assert classify_url("https://caro.sl/x") == (QRClass.SHORTLINK, None)
    assert classify_url("https://wa.me/123") == (QRClass.CTA, None)
    # unknown host is treated as a shortlink so it still gets resolved, not dropped
    assert classify_url("https://random.example.com/x") == (QRClass.SHORTLINK, None)
