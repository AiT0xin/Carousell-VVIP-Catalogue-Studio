"""Shared SSRF guard for QR live-verification — single source of truth.

A QR decoded out of an uploaded PDF is fully attacker-controlled, so before the
live check ever dereferences a decoded URL it must pass through here. Without
this gate the server-side fetch could hit internal IPs, cloud-metadata
endpoints, or localhost admin ports. A QR that points anywhere off the Carousell
ecosystem isn't a valid merchant link anyway, so callers flag it "dead" rather
than fetching it.

Both the in-process verifier (studio/qr.py) and the isolated subprocess worker
(studio/qr_worker.py) import from here, so the allowlist can never drift between
them. Keep this module dependency-light (stdlib only) so the subprocess worker
stays cheap to import.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Only ever fetch URLs on the Carousell ecosystem.
ALLOWED_VERIFY_DOMAINS = (
    "carousell.sg",
    "carousell.com",
    "carousell.com.my",
    "carousell.ph",
    "caro.sl",
)


def is_verifiable_url(url: str) -> bool:
    """True only for http(s) URLs on a known Carousell host — blocks SSRF.

    Matches a base domain exactly or as a proper subdomain (``host == domain``
    or ``host.endswith("." + domain)``), so lookalikes like ``evilcarousell.sg``
    and ``carousell.sg.attacker.com`` are both rejected.
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    return any(
        host == d or host.endswith("." + d) for d in ALLOWED_VERIFY_DOMAINS
    )
