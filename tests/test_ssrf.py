"""SSRF guard — the security-critical gate on every live QR fetch.

A QR is decoded from an attacker-controlled PDF, so is_verifiable_url() is the
only thing standing between "verify this link" and a server-side fetch of an
internal IP or cloud-metadata endpoint. These tests lock that behavior down.
"""
from studio.ssrf import is_verifiable_url as v


def test_allows_carousell_hosts():
    assert v("https://www.carousell.sg/u/foo/")
    assert v("https://carousell.sg/u/foo/")
    assert v("http://carousell.com.my/u/x")
    assert v("https://carousell.ph/u/x")
    assert v("https://caro.sl/abcd")


def test_allows_proper_subdomains():
    assert v("https://sell.carousell.sg/u/x/")


def test_rejects_lookalike_domains():
    # prefix and suffix lookalikes must both fail
    assert not v("https://evilcarousell.sg/x")
    assert not v("https://carousell.sg.attacker.com/x")


def test_rejects_ssrf_targets():
    assert not v("http://169.254.169.254/latest/meta-data/")  # cloud metadata
    assert not v("http://localhost:8501/")
    assert not v("http://127.0.0.1/")
    assert not v("http://[::1]/")


def test_rejects_non_http_schemes():
    assert not v("file:///etc/passwd")
    assert not v("ftp://carousell.sg/x")
    assert not v("gopher://carousell.sg/x")


def test_rejects_garbage():
    assert not v("")
    assert not v("not a url")
    assert not v("://missing-scheme")
